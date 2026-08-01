"""
Επιστρέφει env dict για subprocess.run(["docker", ...], env=...) που δείχνει
στο σωστό docker-socket-proxy ανάλογα με το είδος της ενέργειας.

Χρήση (flat import, ίδιο pattern με το lib/redact.py):
    from docker_env import docker_env
    subprocess.run(["docker", "restart", name], env=docker_env("lifecycle"), ...)
    subprocess.run(["docker", "inspect", ...], env=docker_env("read"), ...)
"""
import os

_PROXY_ENV_VARS = {
    "read": "DOCKER_READ_PROXY",
    "lifecycle": "DOCKER_LIFECYCLE_PROXY",
    "maintenance": "DOCKER_MAINTENANCE_PROXY",
}


def docker_env(proxy: str) -> dict:
    """
    proxy: "read" | "lifecycle" | "maintenance"

    Ρίχνει ValueError αν δοθεί άγνωστο proxy name (typo-proofing — καλύτερα
    να σκάσει αμέσως στο tool παρά να πέσει σιωπηλά πίσω στο host socket)
    ή αν το αντίστοιχο env var λείπει (π.χ. compose file δεν το περνάει).
    """
    if proxy not in _PROXY_ENV_VARS:
        raise ValueError(
            f"Unknown proxy '{proxy}'. Valid: {list(_PROXY_ENV_VARS)}"
        )
    var_name = _PROXY_ENV_VARS[proxy]
    host = os.environ.get(var_name)
    if not host:
        raise RuntimeError(
            f"{var_name} is not set — check docker-compose.proxies.yml env section."
        )
    return {**os.environ, "DOCKER_HOST": host}
