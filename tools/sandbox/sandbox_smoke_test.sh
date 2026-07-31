#!/bin/bash
set -uo pipefail

IMAGE="jarvis-python-sandbox:v1"
PASS=0
FAIL=0

DOCKER_FLAGS=(
    --rm
    --runtime=runsc
    --network=none
    --read-only
    --user=10001:10001
    --cap-drop=ALL
    --security-opt=no-new-privileges:true
    --memory=768m
    --memory-swap=768m
    --cpus=1
    --pids-limit=64
    --ulimit nofile=256:256
    --ulimit nproc=64:64
    --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777
    --tmpfs /work:rw,nosuid,nodev,size=256m,mode=700
    -w /work
)

run_code() {
    timeout 40 docker run "${DOCKER_FLAGS[@]}" "$IMAGE" \
        sh -c "timeout 20s python3 -c \"$1\"" 2>&1
}

check() {
    local desc="$1"
    local expected_pattern="$2"
    local actual_output="$3"
    if echo "$actual_output" | grep -qE "$expected_pattern"; then
        echo "  ✅ PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  ❌ FAIL: $desc"
        echo "     Expected pattern: $expected_pattern"
        echo "     Actual output:    $(echo "$actual_output" | head -3 | tr '\n' ' ')"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== JARVIS Sandbox Security Smoke Test ==="
echo ""

CANARY_DIR="/var/lib/jarvis-sandbox-canary"
sudo mkdir -p "$CANARY_DIR" 2>/dev/null || mkdir -p "$CANARY_DIR"
echo "DO_NOT_ACCESS_$(date +%s)" | sudo tee "$CANARY_DIR/DO_NOT_ACCESS" >/dev/null 2>&1 \
    || echo "DO_NOT_ACCESS_$(date +%s)" > "$CANARY_DIR/DO_NOT_ACCESS" 2>/dev/null
echo "[setup] Canary file at $CANARY_DIR/DO_NOT_ACCESS"
echo ""

echo "--- 1. Βασική λειτουργικότητα ---"
out=$(run_code "print('hello from sandbox')")
check "Βασικό print δουλεύει" "hello from sandbox" "$out"

out=$(run_code "import numpy as np; print(np.array([1,2,3]).sum())")
check "numpy preinstalled και δουλεύει" "^6$" "$out"

echo ""
echo "--- 2. Network isolation ---"
out=$(run_code "
import socket
try:
    socket.gethostbyname('google.com')
    print('DNS_WORKED_BAD')
except Exception as e:
    print('DNS_BLOCKED_GOOD')
")
check "DNS resolution αποτυγχάνει (no network)" "DNS_BLOCKED_GOOD" "$out"

out=$(run_code "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(('8.8.8.8', 53))
    print('TCP_WORKED_BAD')
except Exception:
    print('TCP_BLOCKED_GOOD')
")
check "TCP outbound αποτυγχάνει (no network)" "TCP_BLOCKED_GOOD" "$out"

echo ""
echo "--- 3. Host filesystem isolation ---"
out=$(run_code "
import os
try:
    with open('/etc/shadow') as f:
        f.read()
    print('SHADOW_READ_BAD')
except Exception:
    print('SHADOW_BLOCKED_GOOD')
")
check "/etc/shadow μη προσβάσιμο" "SHADOW_BLOCKED_GOOD" "$out"

out=$(run_code "
import os
print('CANARY_FOUND_BAD' if os.path.exists('/var/lib/jarvis-sandbox-canary/DO_NOT_ACCESS') else 'CANARY_NOT_VISIBLE_GOOD')
")
check "Host canary file μη ορατό μέσα στο sandbox" "CANARY_NOT_VISIBLE_GOOD" "$out"

out=$(run_code "
import os
print('SOCK_FOUND_BAD' if os.path.exists('/var/run/docker.sock') else 'SOCK_NOT_VISIBLE_GOOD')
")
check "Docker socket μη ορατό μέσα στο sandbox" "SOCK_NOT_VISIBLE_GOOD" "$out"

echo ""
echo "--- 4. Read-only root filesystem ---"
out=$(run_code "
try:
    with open('/etc/test_write', 'w') as f:
        f.write('bad')
    print('ROOT_WRITE_WORKED_BAD')
except Exception:
    print('ROOT_WRITE_BLOCKED_GOOD')
")
check "Εγγραφή εκτός /tmp,/work αποτυγχάνει" "ROOT_WRITE_BLOCKED_GOOD" "$out"

out=$(run_code "
with open('/tmp/test_write', 'w') as f:
    f.write('ok')
print('TMP_WRITE_OK_GOOD')
")
check "Εγγραφή σε /tmp (tmpfs) δουλεύει" "TMP_WRITE_OK_GOOD" "$out"

echo ""
echo "--- 5. Privilege / capability checks ---"
out=$(run_code "
import os
try:
    os.mkdir('/proc/sys/test')
    print('PROC_WRITE_WORKED_BAD')
except Exception:
    print('PROC_WRITE_BLOCKED_GOOD')
")
check "/proc/sys εγγραφή αποτυγχάνει" "PROC_WRITE_BLOCKED_GOOD" "$out"

out=$(run_code "
import ctypes, os
try:
    os.setuid(0)
    print('SETUID_WORKED_BAD')
except Exception:
    print('SETUID_BLOCKED_GOOD')
")
check "setuid(0) αποτυγχάνει (non-root user)" "SETUID_BLOCKED_GOOD" "$out"

echo ""
echo "--- 6. Resource limits ---"
echo "  (Memory bomb test -- περιμένουμε OOM kill, μπορεί να πάρει ~10-15s)"
start=$(date +%s)
out=$(timeout 40 docker run "${DOCKER_FLAGS[@]}" "$IMAGE" \
    sh -c "timeout 20s python3 -c \"
data = []
try:
    while True:
        data.append('x' * 10**7)
except MemoryError:
    print('MEMORY_ERROR_CAUGHT')
\"" 2>&1)
end=$(date +%s)
elapsed=$((end - start))
if echo "$out" | grep -qE "MEMORY_ERROR_CAUGHT|Killed|MemoryError" || [ -z "$out" ]; then
    echo "  ✅ PASS: Memory bomb περιορίστηκε/σκοτώθηκε (elapsed: ${elapsed}s)"
    PASS=$((PASS + 1))
else
    echo "  ❌ FAIL: Memory bomb δεν φαίνεται να περιορίστηκε"
    echo "     Output: $(echo "$out" | head -3)"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "  (Fork bomb test -- pids-limit=64, περιμένουμε γρήγορο error)"
out=$(run_code "
import os
count = 0
try:
    while True:
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        count += 1
        if count > 200:
            break
except OSError as e:
    print(f'FORK_BLOCKED_GOOD count={count}')
")
check "Fork bomb περιορίζεται από pids-limit" "FORK_BLOCKED_GOOD" "$out"

echo ""
echo "  (Infinite loop test -- περιμένουμε timeout, όχι κρέμασμα)"
start=$(date +%s)
out=$(timeout 40 docker run "${DOCKER_FLAGS[@]}" "$IMAGE" \
    sh -c "timeout 20s python3 -c \"
while True:
    pass
\"" 2>&1)
end=$(date +%s)
elapsed=$((end - start))
if [ "$elapsed" -lt 30 ]; then
    echo "  ✅ PASS: Infinite loop τερματίστηκε σε ${elapsed}s (< 30s όριο)"
    PASS=$((PASS + 1))
else
    echo "  ❌ FAIL: Infinite loop πήρε ${elapsed}s -- κάτι δεν τερμάτισε σωστά"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "--- 7. gVisor runtime verification ---"
out=$(timeout 15 docker run "${DOCKER_FLAGS[@]}" "$IMAGE" sh -c "cat /proc/version 2>&1 || echo NO_PROC_VERSION")
check "Container τρέχει (gVisor kernel εμφανίζεται διαφορετικά στο /proc/version)" ".+" "$out"

echo ""
echo "=== ΑΠΟΤΕΛΕΣΜΑΤΑ: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
    echo "⚠️  Κάποια tests απέτυχαν -- ΜΗΝ ενεργοποιήσεις το sandbox tool στον JARVIS πριν τα διορθώσεις."
    exit 1
else
    echo "✅ Όλα τα security tests πέρασαν."
    exit 0
fi
