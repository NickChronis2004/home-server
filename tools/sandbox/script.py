"""
JARVIS Sandbox Tool -- v1

Εκτελεί Python κώδικα μέσα σε πλήρως απομονωμένο gVisor container.

ΣΧΕΔΙΑΣΤΙΚΗ ΑΡΧΗ (μην το σπάσεις σε μελλοντικά edits):
    Το μόνο input που δέχεται αυτό το tool είναι μια συμβολοσειρά κώδικα
    (η παράμετρος "code"). ΤΙΠΟΤΑ άλλο από τον caller (JARVIS/LLM) δεν
    επηρεάζει τα docker flags, resource limits, mounts, ή security
    options. Αυτά είναι ΟΛΑ hardcoded εδώ μέσα. Αν χρειαστεί ποτέ να
    γίνουν configurable, πρέπει να περάσουν από ρητό, review-ed
    allowlist στο policy.yaml -- όχι από free-form input.

    Το LLM στέλνει DATA. Αυτό το tool αποφασίζει COMMANDS.

    Tier: το tool ΔΕΝ μπαίνει στα WRITE_TOOL_NAMES/EMERGENCY_TOOL_NAMES
    sets του orchestrator (main.py) -- άρα εκτελείται στο default
    "read_only" path χωρίς confirm gate, lockdown check, ή write-tools
    check. Αυτό είναι σκόπιμο: το container είναι πλήρως isolated
    (gVisor, no network, no host access, ephemeral), άρα δεν χρειάζεται
    ανθρώπινη επιβεβαίωση σε κάθε κλήση. Αν αυτή η παραδοχή πάψει να
    ισχύει (π.χ. προστεθεί network access ή host mounts σε μελλοντική
    version), το tool name πρέπει να προστεθεί στο WRITE_TOOL_NAMES
    ώστε να περνάει από confirm gate.

    ΓΙΑΤΙ stdin ΚΑΙ ΟΧΙ docker cp:
    Αρχική έκδοση χρησιμοποιούσε "docker create" + "docker cp" + "docker
    start" ώστε να περάσει τον κώδικα μέσα στο container χωρίς bind
    mount. Αυτό απέτυχε σε πραγματικό testing: το "docker cp" σε
    container με --read-only αποτυγχάνει με "container rootfs is marked
    read-only", ΑΚΟΜΑ ΚΙ ΟΤΑΝ ο προορισμός είναι μέσα σε tmpfs mount
    (/work) -- το Docker ελέγχει το read-only flag σε επίπεδο ολόκληρου
    container πριν καν φτάσει στο συγκεκριμένο mount point. Η λύση:
    περνάμε τον κώδικα μέσω stdin σε ένα ενιαίο "docker run -i", ο
    Python τον διαβάζει με "python3 -". Απλούστερο (ένα subprocess call
    αντί για τρία) και δεν χρειάζεται καθόλου write στο container πριν
    την εκτέλεση.
"""

import subprocess
import os
import sys
import json
import time

sys.path.insert(0, "/app/jarvis/lib")
from redact import redact  # noqa: E402  (ίδιο pattern με τα υπόλοιπα tools)

# ---- Σταθερές, hardcoded, δεν αλλάζουν από input ----

IMAGE = "jarvis-python-sandbox:v1"
TIMEOUT_SECONDS = 20            # χρόνος εκτέλεσης μέσα στο container
MAX_CODE_SIZE_BYTES = 64 * 1024        # 64 KB
MAX_OUTPUT_BYTES = 512 * 1024          # 512 KB per stream (stdout/stderr)

# ΣΗΜΑΝΤΙΚΟ: ο orchestrator (main.py) βάζει δικό του hard timeout=120s
# γύρω από ΟΛΗ την εκτέλεση αυτού του script.py (subprocess.run(...,
# timeout=120)). Με "docker run --rm -i" (ένα μόνο subprocess call, όχι
# create+cp+start), το worst-case budget είναι πολύ πιο απλό να
# υπολογιστεί: μόνο το ίδιο το docker run, με --rm το container
# αυτοκαθαρίζεται μόνο του μόλις τερματίσει -- δεν χρειάζεται καν
# ξεχωριστό cleanup βήμα.
RUN_TIMEOUT_BUFFER = 10        # buffer πάνω από το TIMEOUT_SECONDS (docker overhead)
# Worst case: TIMEOUT_SECONDS + RUN_TIMEOUT_BUFFER = 30s -- ~90s περιθώριο.

DOCKER_FIXED_FLAGS = [
    "--rm",
    "-i",
    "--runtime=runsc",
    "--network=none",
    "--read-only",
    "--user=10001:10001",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--memory=768m",
    "--memory-swap=768m",
    "--cpus=1",
    "--pids-limit=64",
    "--ulimit", "nofile=256:256",
    "--ulimit", "nproc=64:64",
    "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
    "--tmpfs", "/work:rw,nosuid,nodev,size=256m,mode=700",
    "-w", "/work",
]


def _truncate(data: bytes, limit: int):
    """Επιστρέφει (decoded_text, was_truncated)."""
    was_truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    return text, was_truncated


def run(code):
    """
    Εκτελεί τον δοθέντα python κώδικα μέσα σε ephemeral gVisor container.

    Ροή:
      1. validate input (τύπος, μέγεθος, μη-κενό)
      2. docker run -i --rm ... python3 -   (κώδικας μέσω stdin)
      3. μάζεψε stdout/stderr/exit code, με --rm το container
         αυτοκαθαρίζεται μόνο του μόλις τερματίσει

    Επιστρέφει dict. Ποτέ δεν κάνει raise -- ίδιο convention με τα
    υπόλοιπα tools (return {"error": ...} αντί για exceptions).
    """
    if not isinstance(code, str) or not code.strip():
        return {"error": "Το 'code' πρέπει να είναι μη κενό string."}

    if len(code.encode("utf-8")) > MAX_CODE_SIZE_BYTES:
        return {"error": f"Ο κώδικας υπερβαίνει το όριο των {MAX_CODE_SIZE_BYTES} bytes."}

    docker_cmd = (
        ["docker", "run"] + DOCKER_FIXED_FLAGS
        + [IMAGE, "timeout", f"{TIMEOUT_SECONDS}s", "python3", "-"]
    )

    start_time = time.monotonic()
    try:
        result = subprocess.run(
            docker_cmd,
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=TIMEOUT_SECONDS + RUN_TIMEOUT_BUFFER,
        )
        stdout_bytes, stderr_bytes = result.stdout, result.stderr
        exit_code = result.returncode
        hard_timeout = False
    except subprocess.TimeoutExpired as e:
        stdout_bytes = e.stdout or b""
        stderr_bytes = e.stderr or b""
        exit_code = None
        hard_timeout = True

    elapsed = time.monotonic() - start_time

    stdout_text, stdout_trunc = _truncate(stdout_bytes, MAX_OUTPUT_BYTES)
    stderr_text, stderr_trunc = _truncate(stderr_bytes, MAX_OUTPUT_BYTES)

    if hard_timeout:
        termination_reason = "hard_timeout_killed"
    elif elapsed >= TIMEOUT_SECONDS:
        termination_reason = "timeout"
    elif exit_code == 137:
        termination_reason = "killed_oom_or_signal"
    elif exit_code != 0:
        termination_reason = "error_exit"
    else:
        termination_reason = "completed"

    return {
        "untrusted_program_output": {
            "stdout": redact(stdout_text),
            "stdout_truncated": stdout_trunc,
            "stderr": redact(stderr_text),
            "stderr_truncated": stderr_trunc,
        },
        "exit_code": exit_code,
        "termination_reason": termination_reason,
        "elapsed_seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    code_arg = os.environ.get("TOOL_ARG_code", "")
    print(json.dumps(run(code_arg), indent=2, ensure_ascii=False))
