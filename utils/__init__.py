# Utils package

import shlex
import subprocess


def run_shell_command(command: str, timeout: int = 300) -> tuple[bool, str]:
    """
    Safely run a shell command without shell=True injection risk.
    
    Args:
        command: Command string to run
        timeout: Timeout in seconds (default 300)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    if not command or not command.strip():
        return False, "No command provided"
    
    try:
        # Parse command safely - shlex.split handles quotes and escapes properly
        args = shlex.split(command)
        if not args:
            return False, "Empty command after parsing"
        
        result = subprocess.run(
            args,
            timeout=timeout,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True, "Command completed successfully"
        else:
            error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            return False, f"Command failed: {error_msg}"
            
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout} seconds"
    except FileNotFoundError as e:
        return False, f"Command not found: {e}"
    except ValueError as e:
        # shlex.split can raise ValueError on malformed strings
        return False, f"Invalid command syntax: {e}"
    except Exception as e:
        return False, f"Command error: {e}"
