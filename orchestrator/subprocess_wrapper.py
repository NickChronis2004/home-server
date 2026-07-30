import subprocess
from errors import ToolTimeoutError, ToolExecutionError

MAX_OUTPUT_CHARS = 50000

def run_command(command: list, timeout: float = 15):
    """
    Safe subprocess wrapper used by all tools.
    Raises JarvisError subclasses instead of letting raw exceptions leak.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise ToolTimeoutError(
            f"Command timed out after {timeout}s",
            details={"command": command[0]}
        )
    except FileNotFoundError:
        raise ToolExecutionError(
            f"Required executable '{command[0]}' not found"
        )
    except PermissionError:
        raise ToolExecutionError(
            f"Permission denied executing '{command[0]}'"
        )
    except OSError as e:
        raise ToolExecutionError(
            f"OS error running '{command[0]}': {str(e)[:200]}"
        )

    stdout = result.stdout[:MAX_OUTPUT_CHARS]
    stderr = result.stderr[:MAX_OUTPUT_CHARS]

    if result.returncode != 0:
        raise ToolExecutionError(
            "Command exited with non-zero status",
            details={"returncode": result.returncode, "stderr": stderr}
        )

    return stdout
