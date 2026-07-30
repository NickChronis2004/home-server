import os
import json
import yaml
import subprocess
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

from errors import JarvisError, ToolNotFoundError, ManifestError, ModelProviderError, ToolTimeoutError, ToolExecutionError

BASE_DIR = Path("/app/jarvis")
TOOLS_DIR = BASE_DIR / "tools"
PENDING_FILE = BASE_DIR / "logs" / ".pending_confirmation.json"
PENDING_EXPIRY_SECONDS = 120
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
JARVIS_MODEL = os.environ.get("JARVIS_MODEL", "gpt-4o-mini")

app = FastAPI()

@app.exception_handler(JarvisError)
async def handle_jarvis_error(request: Request, exc: JarvisError):
    print(f"[JARVIS] error_code={exc.error_code} message={exc.message}", flush=True)
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.error_code, "message": exc.message, "retryable": exc.retryable}}
    )

@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    print(f"[JARVIS] UNEXPECTED ERROR: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred.", "retryable": False}}
    )

def discover_tools():
    tools = {}
    if not TOOLS_DIR.exists():
        return tools
    for tool_dir in TOOLS_DIR.iterdir():
        if not tool_dir.is_dir():
            continue
        manifest_path = tool_dir / "manifest.yaml"
        script_path = tool_dir / "script.py"
        if not manifest_path.exists() or not script_path.exists():
            continue
        try:
            with open(manifest_path) as f:
                manifest = yaml.safe_load(f)
            if not isinstance(manifest, dict) or "name" not in manifest:
                print(f"[JARVIS] Skipping invalid manifest: {tool_dir.name}", flush=True)
                continue
            tools[manifest["name"]] = {"manifest": manifest, "script_path": str(script_path)}
        except yaml.YAMLError as e:
            print(f"[JARVIS] Skipping tool with invalid YAML: {tool_dir.name}: {e}", flush=True)
            continue
    return tools

def execute_tool(tool_name, arguments, tools):
    if tool_name not in tools:
        raise ToolNotFoundError(f"Unknown tool: {tool_name}")

    script_path = tools[tool_name]["script_path"]
    env = os.environ.copy()
    for key, value in arguments.items():
        env[f"TOOL_ARG_{key}"] = str(value)

    try:
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True, text=True, timeout=30, env=env
        )
    except subprocess.TimeoutExpired:
        raise ToolTimeoutError(f"Tool '{tool_name}' timed out")

    if result.returncode != 0:
        raise ToolExecutionError(
            f"Tool '{tool_name}' failed",
            details={"stderr": result.stderr[:500]}
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"output": result.stdout[:2000]}

def build_openai_tools_schema(tools):
    schema = []
    for name, data in tools.items():
        m = data["manifest"]
        params = m.get("parameters", [])
        properties = {}
        required = []
        for p in params:
            properties[p["name"]] = {"type": p.get("type", "string"), "description": p.get("description", "")}
            if p.get("required"):
                required.append(p["name"])
        schema.append({
            "type": "function",
            "function": {
                "name": m["name"],
                "description": m["description"],
                "parameters": {"type": "object", "properties": properties, "required": required}
            }
        })
    return schema

def get_pending_confirmation():
    if not PENDING_FILE.exists():
        return None
    try:
        data = json.loads(PENDING_FILE.read_text())
    except json.JSONDecodeError:
        return None
    if time.time() - data.get("created_at", 0) > PENDING_EXPIRY_SECONDS:
        return None
    return data

def clear_pending_confirmation():
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()

@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "jarvis", "object": "model", "owned_by": "jarvis"}]}

@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    tools = discover_tools()
    messages = request.get("messages", [])

    last_user_message = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_message = (m.get("content") or "").strip()
            break

    if last_user_message == "/confirm":
        pending = get_pending_confirmation()
        if not pending:
            return {
                "id": "jarvis-response", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "There is no pending action to confirm, or it has expired. Please make a new request first."}, "finish_reason": "stop"}]
            }
        clear_pending_confirmation()
        try:
            result = execute_tool(pending["tool"], {"container_name": pending["container_name"], "confirmed": "true"}, tools)
            print(f"[JARVIS] CONFIRMED tool={pending['tool']} target={pending['container_name']} result={result.get('status')}", flush=True)
            content = f"Done. {json.dumps(result, ensure_ascii=False)}"
        except JarvisError as e:
            content = f"The confirmed action failed: {e.message}"
        return {
            "id": "jarvis-response", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]
        }

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": JARVIS_MODEL,
        "messages": messages,
        "tools": build_openai_tools_schema(tools),
        "tool_choice": "auto"
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OPENAI_URL, headers=headers, json=payload)
            result = resp.json()
    except httpx.TimeoutException:
        raise ModelProviderError("The AI model provider timed out.")
    except httpx.ConnectError:
        raise ModelProviderError("Could not connect to the AI model provider.")

    if "error" in result:
        raise ModelProviderError(f"Model provider returned an error: {result['error'].get('message', 'unknown')}")

    choices = result.get("choices")
    if not choices:
        raise ModelProviderError("Model provider returned no choices.")

    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])

    if tool_calls:
        messages.append(message)
        for call in tool_calls:
            fn_name = call["function"]["name"]
            try:
                fn_args = json.loads(call["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                fn_args = {}

            fn_args["confirmed"] = "false"

            try:
                tool_result = execute_tool(fn_name, fn_args, tools)
                success = True
            except JarvisError as e:
                tool_result = {"error": e.message}
                success = False

            print(f"[JARVIS] tool={fn_name} args={fn_args} success={success}", flush=True)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        payload["messages"] = messages
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(OPENAI_URL, headers=headers, json=payload)
                result = resp.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            return {
                "id": "jarvis-response", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "The action completed, but I couldn't generate a final response. Please check the results directly."}, "finish_reason": "stop"}]
            }
        choices = result.get("choices", [{}])
        message = choices[0].get("message", {}) if choices else {}

    return {
        "id": "jarvis-response", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": message.get("content", "")}, "finish_reason": "stop"}]
    }

@app.get("/health")
async def health():
    return {"status": "ok", "tools_loaded": len(discover_tools())}
