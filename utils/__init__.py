import contextlib
import os
import signal
import subprocess
import time


def run_shell_command(command: str, timeout: int = 300) -> tuple[bool, str, str]:
    """
    Run a shell command in its own process group, with an honest timeout.

    The command runs via a shell, so pipes/redirects work. It is started
    with start_new_session=True so that on timeout the ENTIRE process
    group is killed — not just the shell. Without this, children (e.g. an
    rsync in a post-backup script) survive as orphans and keep running
    after we report a timeout, so the report is a lie in both directions:
    the UI claims failure while the work may quietly succeed, and nothing
    bounds the orphan's runtime. (Discovered 2026-07-24: a 223 MB
    post-backup rsync "timed out" in the UI at 300s and then completed as
    an orphan 62s later.)

    Args:
        command: Command string to run (supports pipes, redirects, etc.)
        timeout: Timeout in seconds (default 300)

    Returns:
        Tuple of (success: bool, message: str, stdout: str)
    """
    if not command or not command.strip():
        return False, "No command provided", ""

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the whole group: TERM first for a clean shutdown,
            # then KILL for anything that ignored it. Each call guarded
            # individually — the group may already be gone (ESRCH) or
            # contain reaped members macOS refuses to signal (EPERM).
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)
            time.sleep(2)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
            return (
                False,
                f"Command timed out after {timeout} seconds and was stopped",
                stdout or "",
            )

        if proc.returncode == 0:
            return True, "Command completed successfully", stdout or ""
        error_msg = stderr.strip() if stderr else f"Exit code {proc.returncode}"
        return False, f"Command failed: {error_msg}", stdout or ""

    except Exception as e:
        return False, f"Command error: {e}", ""
