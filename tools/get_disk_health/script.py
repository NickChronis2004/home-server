#!/usr/bin/env python3
"""get_disk_health — read-only, calls the os-helper host daemon."""

import sys
import json
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from os_helper_client import call_os_helper


def main():
    result = call_os_helper("/get_disk_health")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
