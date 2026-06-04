# Utils package

import subprocess


def run_shell_command(command: str, timeout: int = 300) -> tuple[bool, str]:
    """
    Run a shell command.

    Args:
        command: Command string to run (supports pipes, redirects, etc.)
        timeout: Timeout in seconds (default 300)

    Returns:
        Tuple of (success: bool, message: str)
    """
    if not command or not command.strip():
        return False, "No command provided"

    try:
        result = subprocess.run(
            command, shell=True, timeout=timeout, capture_output=True, text=True
        )

        if result.returncode == 0:
            return True, "Command completed successfully"
        else:
            error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            return False, f"Command failed: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout} seconds"
    except Exception as e:
        return False, f"Command error: {e}"
