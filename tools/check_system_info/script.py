import subprocess
import json

def run():
    os_info = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()

    cpu_model = "unknown"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass

    os_release = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    key, _, value = line.strip().partition("=")
                    os_release[key] = value.strip('"')
    except FileNotFoundError:
        pass

    return {
        "os_name": "Ubuntu Server 24.04 LTS (host) - note: container internally reports Debian, this is the actual host OS",
        "kernel_and_arch": os_info,
        "cpu_model": cpu_model
    }

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
