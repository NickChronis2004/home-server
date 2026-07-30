import subprocess
import json

def run():
    # Memory info
    mem_result = subprocess.run(["free", "-h"], capture_output=True, text=True)
    mem_lines = mem_result.stdout.strip().split("\n")
    mem_data = mem_lines[1].split() if len(mem_lines) > 1 else []

    # CPU load average
    with open("/proc/loadavg") as f:
        load = f.read().split()[:3]

    # CPU count
    cpu_result = subprocess.run(["nproc"], capture_output=True, text=True)
    cpu_count = cpu_result.stdout.strip()

    return {
        "cpu_cores": cpu_count,
        "load_average_1min": load[0],
        "load_average_5min": load[1],
        "load_average_15min": load[2],
        "memory_total": mem_data[1] if len(mem_data) > 1 else "unknown",
        "memory_used": mem_data[2] if len(mem_data) > 2 else "unknown",
        "memory_available": mem_data[6] if len(mem_data) > 6 else "unknown"
    }

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
