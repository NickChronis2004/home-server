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
from audit import init_db, log_tool_call

BASE_DIR = Path("/app/jarvis")
TOOLS_DIR = BASE_DIR / "tools"
PENDING_FILE = BASE_DIR / "logs" / ".pending_confirmation.json"
PENDING_EXPIRY_SECONDS = 120
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
JARVIS_MODEL = os.environ.get("JARVIS_MODEL", "gpt-4o-mini")
WRITE_TOOLS_ENABLED = os.environ.get("JARVIS_WRITE_TOOLS_ENABLED", "true").lower() == "true"
WRITE_TOOL_NAMES = {"restart_container", "stop_container", "start_container"}
EMERGENCY_TOOL_NAMES = {"protocol_snowfall", "protocol_blackout"}
LOCKDOWN_FILE = BASE_DIR / "logs" / ".lockdown"

def is_lockdown_active():
    return LOCKDOWN_FILE.exists()

app = FastAPI()
init_db()

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
    tier = "emergency" if tool_name in EMERGENCY_TOOL_NAMES else ("write" if tool_name in WRITE_TOOL_NAMES else "read_only")
    confirmed = str(arguments.get("confirmed", "false")).lower() == "true"
    start = time.monotonic()
    if tool_name in WRITE_TOOL_NAMES and is_lockdown_active():
        audit_id = log_tool_call(tool_name, tier, arguments, "denied",
                       result_summary="Blocked: system is in lockdown (Protocol Snowfall active)",
                       error_code="LOCKDOWN_ACTIVE", confirmed=confirmed)
        raise JarvisError(
            "The system is currently in emergency lockdown. Write actions are disabled; diagnostics remain available. "
            "Recovery requires direct server access (Protocol Daybreak).",
            details={"tool": tool_name, "audit_id": audit_id}
        )
    if tool_name not in tools:
        audit_id = log_tool_call(tool_name, tier, arguments, "error",
                       result_summary="Unknown tool", error_code="TOOL_NOT_FOUND",
                       confirmed=confirmed)
        raise ToolNotFoundError(f"Unknown tool: {tool_name}", details={"audit_id": audit_id})
    if tool_name in WRITE_TOOL_NAMES and not WRITE_TOOLS_ENABLED:
        audit_id = log_tool_call(tool_name, tier, arguments, "denied",
                       result_summary="Write actions disabled system-wide",
                       error_code="WRITE_TOOLS_DISABLED", confirmed=confirmed)
        raise JarvisError(
            "Write actions are currently disabled system-wide. Ask the administrator to re-enable them.",
            details={"tool": tool_name, "audit_id": audit_id}
        )
    script_path = tools[tool_name]["script_path"]
    env = os.environ.copy()
    for key, value in arguments.items():
        env[f"TOOL_ARG_{key}"] = str(value)
    try:
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True, text=True, timeout=120, env=env
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        audit_id = log_tool_call(tool_name, tier, arguments, "error",
                       result_summary="Tool timed out", duration_ms=duration_ms,
                       error_code="TOOL_TIMEOUT", confirmed=confirmed)
        raise ToolTimeoutError(f"Tool '{tool_name}' timed out", details={"audit_id": audit_id})
    duration_ms = int((time.monotonic() - start) * 1000)
    if result.returncode != 0:
        audit_id = log_tool_call(tool_name, tier, arguments, "error",
                       result_summary=result.stderr[:500], duration_ms=duration_ms,
                       error_code="TOOL_EXECUTION_FAILED", confirmed=confirmed)
        raise ToolExecutionError(
            f"Tool '{tool_name}' failed",
            details={"stderr": result.stderr[:500], "audit_id": audit_id}
        )
    try:
        parsed = json.loads(result.stdout)
        is_logical_error = isinstance(parsed, dict) and "error" in parsed
        audit_id = log_tool_call(tool_name, tier, arguments,
                       "error" if is_logical_error else "success",
                       result_summary=json.dumps(parsed, ensure_ascii=False)[:500],
                       duration_ms=duration_ms,
                       error_code="TOOL_LOGICAL_ERROR" if is_logical_error else None,
                       confirmed=confirmed)
        if isinstance(parsed, dict):
            parsed["_audit_id"] = audit_id
        return parsed
    except json.JSONDecodeError:
        audit_id = log_tool_call(tool_name, tier, arguments, "success",
                       result_summary=result.stdout[:500], duration_ms=duration_ms,
                       confirmed=confirmed)
        return {"output": result.stdout[:2000], "_audit_id": audit_id}

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
            confirmed_args = {k: v for k, v in pending.items() if k not in ("tool", "created_at")}
            confirmed_args["confirmed"] = "true"
            result = execute_tool(pending["tool"], confirmed_args, tools)
            print(f"[JARVIS] CONFIRMED tool={pending['tool']} args={confirmed_args} result={result.get('status')}", flush=True)
            content = f"Done. {json.dumps(result, ensure_ascii=False)}"
        except JarvisError as e:
            content = f"The confirmed action failed: {e.message} [audit_id: {e.details.get('audit_id', 'n/a')}]"
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
                tool_result = {"error": e.message, "_audit_id": e.details.get("audit_id")}
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
