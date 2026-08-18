"""
trivy_scan — read-only CVE vulnerability scan of container images.

Routes through the maintenance proxy (needs docker run / container-create,
same as sandbox and protocol_permafrost) rather than the read proxy, because
Trivy needs to spin up its own ephemeral container to inspect image layers.

Parameters (via TOOL_ARG_* env vars, per the standard JARVIS tool convention):
    target (optional): a single container name to scan (e.g. "jellyfin").
        If omitted, scans every currently-running core-service container,
        discovered dynamically via `docker ps` (never hardcoded), mirroring
        the volume-discovery pattern already used in protocol_permafrost.

Caching:
    Trivy's CVE database (~108MB) is persisted in a named Docker volume
    (trivy-cache) mounted into each ephemeral scan container. Trivy itself
    skips re-downloading if the cached DB is under 24h old, so repeat scans
    after the first are seconds, not minutes.

Concurrency:
    In full-scan mode (no target given), each image is scanned in its own
    subprocess concurrently (ThreadPoolExecutor) rather than sequentially,
    so total wall-clock time stays close to a single scan's time rather than
    the sum of all of them.
"""

import sys
import os
import json
import subprocess


sys.path.insert(0, "/app/jarvis/lib")
from docker_env import docker_env  # noqa: E402

TRIVY_IMAGE = "aquasec/trivy"
TRIVY_CACHE_VOLUME = "trivy-cache"
SCAN_TIMEOUT_FLAG = "10m"          # Trivy's own internal DB-download timeout
SUBPROCESS_TIMEOUT_SECONDS = 720   # hard ceiling per image, safety net


def get_running_containers():
    """Discover currently-running containers via the read proxy — never hardcoded."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}:{{.Image}}"],
        env=docker_env("read"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None, f"docker ps failed: {result.stderr.strip()}"

    containers = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        name, _, image = line.partition(":")
        containers.append({"name": name, "image": image})
    return containers, None


def scan_image(image_ref, container_name=None):
    """Run a single Trivy scan against one image, via an ephemeral container
    routed through the maintenance proxy. Returns a summarized dict, never
    the raw Trivy table — that's for the tool layer to keep chat output sane.
    """
    cmd = [
        "docker", "run", "--rm",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{TRIVY_CACHE_VOLUME}:/root/.cache/trivy",
        TRIVY_IMAGE,
        "image",
        "--timeout", SCAN_TIMEOUT_FLAG,
        "--format", "json",
        "--severity", "MEDIUM,HIGH,CRITICAL",
        "--quiet",
        image_ref,
    ]

    label = container_name or image_ref

    try:
        result = subprocess.run(
            cmd,
            env=docker_env("maintenance"),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "target": label,
            "image": image_ref,
            "error": f"scan exceeded {SUBPROCESS_TIMEOUT_SECONDS}s timeout",
        }

    if result.returncode != 0:
        return {
            "target": label,
            "image": image_ref,
            "error": f"trivy exited {result.returncode}: {result.stderr.strip()[:500]}",
        }

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "target": label,
            "image": image_ref,
            "error": "could not parse trivy JSON output",
        }

    total = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
    fixable = 0
    top_findings = []

    for res in raw.get("Results", []) or []:
        for vuln in res.get("Vulnerabilities", []) or []:
            sev = vuln.get("Severity", "UNKNOWN")
            if sev in total:
                total[sev] += 1
            if vuln.get("FixedVersion"):
                fixable += 1
            if sev in ("CRITICAL", "HIGH") and len(top_findings) < 10:
                top_findings.append({
                    "id": vuln.get("VulnerabilityID"),
                    "severity": sev,
                    "package": vuln.get("PkgName"),
                    "installed": vuln.get("InstalledVersion"),
                    "fixed": vuln.get("FixedVersion") or None,
                })

    return {
        "target": label,
        "image": image_ref,
        "critical": total["CRITICAL"],
        "high": total["HIGH"],
        "medium": total["MEDIUM"],
        "fixable_count": fixable,
        "top_findings": top_findings,
    }


def main():
    target = os.environ.get("TOOL_ARG_target", "").strip()

    if target:
        containers, err = get_running_containers()
        if err:
            print(json.dumps({"error": err}))
            sys.exit(1)

        match = next((c for c in containers if c["name"] == target), None)
        if not match:
            print(json.dumps({
                "error": f"no running container named '{target}' found",
                "known_containers": [c["name"] for c in containers],
            }))
            sys.exit(1)

        outcome = scan_image(match["image"], container_name=match["name"])
        print(json.dumps({"scanned": 1, "results": [outcome]}, indent=2))
        return

    containers, err = get_running_containers()
    if err:
        print(json.dumps({"error": err}))
        sys.exit(1)

    if not containers:
        print(json.dumps({"error": "no running containers found"}))
        sys.exit(1)

    # Sequential, not parallel: Trivy's on-disk cache (BoltDB) doesn't handle
    # concurrent writers safely — parallel scans against the same trivy-cache
    # volume were timing out waiting for the cache lock. With the DB already
    # cached, each scan only takes a few seconds, so sequential is fast enough
    # in practice (2026-08-18 finding).
    results = [scan_image(c["image"], c["name"]) for c in containers]

    severity_order = {"error": -1}
    results.sort(
        key=lambda r: (
            severity_order.get("error", 0) if "error" in r else 0,
            -(r.get("critical", 0) * 100 + r.get("high", 0) * 10 + r.get("medium", 0)),
        )
    )

    print(json.dumps({"scanned": len(results), "results": results}, indent=2))


if __name__ == "__main__":
    main()
