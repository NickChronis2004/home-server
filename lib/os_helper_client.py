"""
lib/os_helper_client.py

Shared client for calling the os-helper host daemon from any JARVIS
tool. Same spirit as lib/docker_env.py — one small, shared helper
rather than duplicating connection/timeout/error handling in every
tool that needs it.
"""

import json
import urllib.request
import urllib.error

OS_HELPER_BASE_URL = "http://host.docker.internal:8787"
REQUEST_TIMEOUT_SECONDS = 8


def call_os_helper(endpoint: str) -> dict:
    """
    GETs a fixed endpoint on the os-helper daemon and returns parsed
    JSON. `endpoint` must start with '/' and match one of the
    daemon's fixed endpoint names (see os_helper.py — there is no
    generic passthrough, so an unknown endpoint returns a clear
    404-shaped error rather than doing anything unexpected).

    Never raises on connection or HTTP-level failure — returns an
    {"error": ...} dict instead, so a tool calling this can surface
    a clean error to the model/user rather than crashing.
    """
    url = f"{OS_HELPER_BASE_URL}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode()
            return json.loads(body)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": f"os-helper returned HTTP {e.code}"}
    except urllib.error.URLError as e:
        # Covers connection refused, timeout, DNS failure on
        # host.docker.internal, etc. — most likely causes: the
        # os-helper systemd service isn't running, or
        # host.docker.internal isn't enabled on this container (see
        # os-helper-DEPLOY.md Section 5).
        return {
            "error": f"could not reach os-helper daemon: {e.reason}",
            "hint": "check `systemctl status os-helper` on the host, "
                    "and confirm extra_hosts is set for host.docker.internal "
                    "in this container's compose config.",
        }
    except json.JSONDecodeError:
        return {"error": "os-helper returned invalid JSON"}
