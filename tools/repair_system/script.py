import subprocess
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app/jarvis/lib")
from docker_env import docker_env

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

PENDING_FILE = Path("/app/jarvis/logs/.pending_confirmation.json")
PENDING_EXPIRY_SECONDS = 120

# Closed enum - the LLM can only pass one of these, never free text.
SUPPORTED_REPAIR_TYPES = ["clean_docker_disk", "clean_build_cache"]

# How old a stopped container must be before it's eligible for removal.
# Deliberately conservative - never touch anything stopped in the last day.
STOPPED_CONTAINER_AGE_FILTER = "24h"


def set_pending(repair_type):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "tool": "repair_system",
        "repair_type": repair_type,
        "created_at": time.time()
    }))


def preview_docker_disk_cleanup():
    """
    Read-only preview of what a clean_docker_disk run would remove, so the
    confirmation message tells the user something concrete instead of a
    blanket warning. Uses the same `docker system df` the diagnose tool uses.
    """
    result = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15, env=docker_env("read")
    )
    rows = [json.loads(line) for line in result.stdout.strip().split("\n") if line]
    reclaimable = {row["Type"]: row["Reclaimable"] for row in rows}
    return reclaimable


def clean_docker_disk():
    """
    Runs docker system prune with deliberately narrow flags:
      - NO --volumes: never touches named volumes (persistent app data).
      - NO -a: never removes images still tagged/in-use, only dangling ones.
      - --filter until=24h: only removes stopped containers/networks/images
        that have been unused for at least 24 hours - never something the
        user just stopped moments ago.
    Build cache is pruned separately via the raw Docker API (see
    _build_prune_via_api) rather than relying on `docker system prune` to
    clear it as a side effect - that side-effect path goes through the
    buildx CLI/context resolution and 403s behind the maintenance proxy
    (missing buildx builder-context state in this container). The API
    call below does the same job cleanly, filtered to the same 24h age
    window so behavior matches what the confirmation message promises.
    """
    result = subprocess.run(
        ["docker", "system", "prune", "--force",
         "--filter", f"until={STOPPED_CONTAINER_AGE_FILTER}"],
        capture_output=True, text=True, timeout=60, env=docker_env("maintenance")
    )
    if result.returncode != 0:
        return {"error": f"Cleanup failed: {result.stderr[:300]}"}

    build_prune_error = None
    try:
        _build_prune_via_api(until=STOPPED_CONTAINER_AGE_FILTER)
    except HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        build_prune_error = f"HTTP {exc.code}: {body}"
    except (URLError, TimeoutError, KeyError, ValueError, RuntimeError) as exc:
        build_prune_error = str(exc)

    after = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15, env=docker_env("read")
    )
    rows = [json.loads(line) for line in after.stdout.strip().split("\n") if line]

    result_dict = {
        "status": "success",
        "repair_type": "clean_docker_disk",
        "prune_output": result.stdout.strip()[:1000],
        "disk_usage_after": rows
    }
    if build_prune_error:
        # Containers/images/networks still got cleaned above - only the
        # build cache portion failed, so report it as a partial issue
        # rather than failing the whole repair.
        result_dict["build_cache_warning"] = f"Build cache cleanup failed: {build_prune_error}"
    return result_dict


def _build_prune_via_api(until=None):
    """
    Calls the Docker Engine API's POST /build/prune directly over the
    maintenance proxy, instead of `docker builder prune` (buildx CLI) or
    relying on `docker system prune` to clear it as a side effect. Both
    of those go through the buildx CLI/context resolution path, which
    expects builder state (~/.docker/buildx) and a dedicated BuildKit
    container (buildx_buildkit_default) that don't exist in this
    container - that mismatch is what surfaces as a 403 from the proxy.
    The raw API endpoint does the same prune without any of that - it's
    exactly what BUILD=1/POST=1 on the maintenance proxy was already
    scoped for.

    until: optional Go duration string (e.g. "24h") to only prune cache
    older than that age, matching the semantics of --filter until=24h.
    If omitted, prunes all build cache regardless of age.
    """
    host = os.environ.get("DOCKER_MAINTENANCE_PROXY", "").strip()
    if not host:
        raise RuntimeError("DOCKER_MAINTENANCE_PROXY is not set.")
    base_url = "http://" + host[len("tcp://"):] if host.startswith("tcp://") else host.rstrip("/")

    with urlopen(f"{base_url}/version", timeout=10) as r:
        api_version = json.load(r)["ApiVersion"]

    query = "all=true"
    if until:
        filters = json.dumps({"until": [until]})
        query = f"filters={quote(filters)}"

    req = Request(f"{base_url}/v{api_version}/build/prune?{query}", data=b"", method="POST")
    with urlopen(req, timeout=60) as r:
        return json.load(r)


def clean_build_cache():
    """
    Runs docker builder prune with no age filter - build cache is always
    safe to remove regardless of age, since it's purely rebuildable
    intermediate layers from `docker build`, never running state or user
    data. The only cost is slower next `docker build` (cache has to be
    regenerated). This never touches images, containers, volumes, or
    networks - only the builder cache.
    """
    try:
        prune_result = _build_prune_via_api()
    except HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        return {"error": f"Build cache cleanup failed: HTTP {exc.code}: {body}"}
    except (URLError, TimeoutError, KeyError, ValueError, RuntimeError) as exc:
        return {"error": f"Build cache cleanup failed: {exc}"}

    after = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15, env=docker_env("read")
    )
    rows = [json.loads(line) for line in after.stdout.strip().split("\n") if line]

    return {
        "status": "success",
        "repair_type": "clean_build_cache",
        "caches_deleted": prune_result.get("CachesDeleted") or [],
        "space_reclaimed_bytes": prune_result.get("SpaceReclaimed", 0),
        "disk_usage_after": rows
    }


def run(repair_type, confirmed):
    if repair_type not in SUPPORTED_REPAIR_TYPES:
        return {"error": f"Unsupported repair_type. Supported: {SUPPORTED_REPAIR_TYPES}"}

    if repair_type == "clean_docker_disk":
        if not confirmed:
            set_pending(repair_type)
            reclaimable = preview_docker_disk_cleanup()
            return {
                "status": "confirmation_required",
                "reclaimable_now": reclaimable,
                "message": (
                    "This will remove dangling (untagged) Docker images, "
                    "stopped containers older than 24 hours, unused networks, "
                    "and build cache older than 24 hours. Named volumes and "
                    "in-use images are never touched. Tell the user to type "
                    "exactly /confirm (nothing else) within 2 minutes to "
                    "proceed. Do not proceed without that exact command from "
                    "the user."
                )
            }
        return clean_docker_disk()

    if repair_type == "clean_build_cache":
        if not confirmed:
            set_pending(repair_type)
            reclaimable = preview_docker_disk_cleanup()
            return {
                "status": "confirmation_required",
                "reclaimable_now": reclaimable,
                "message": (
                    "This will remove ALL Docker build cache, regardless of "
                    "age - this is always safe (rebuildable layers only, "
                    "never user data), but the next `docker build` will be "
                    "slower since the cache has to regenerate. Images, "
                    "containers, volumes, and networks are never touched. "
                    "Tell the user to type exactly /confirm (nothing else) "
                    "within 2 minutes to proceed. Do not proceed without "
                    "that exact command from the user."
                )
            }
        return clean_build_cache()

    return {"error": "Unhandled repair_type."}


if __name__ == "__main__":
    repair_type = os.environ.get("TOOL_ARG_repair_type", "")
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(repair_type, confirmed), indent=2, ensure_ascii=False))
