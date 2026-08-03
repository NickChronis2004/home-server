#!/usr/bin/env python3
"""
get_memory_pressure — read-only, calls the os-helper host daemon.
Note the import path assumption: this expects a shared
lib/os_helper_client.py alongside your existing lib/docker_env.py
(same layout convention as your other tools). Adjust the sys.path
insert below if your tools directory structure differs.
"""
import sys
import json
import os

# Assumes tools live at ~/jarvis/tools/<tool_name>/script.py and the
# shared lib/ sits at ~/jarvis/tools/lib/ — same convention as
# docker_env.py. Adjust if your layout differs.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from os_helper_client import call_os_helper


def main():
    result = call_os_helper("/get_memory_pressure")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
