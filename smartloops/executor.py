"""Smart Loops — Executor: spawns Claude Code sessions to work on tasks."""

import json
import os
import subprocess
import sys

from config import SMARTLOOPS_DIR


SPAWN_FILE = "spawn.json"


def pick_next_task(project_path: str) -> str | None:
    """Parse todo.md, return the first unchecked item, or None."""
    todo_path = os.path.join(project_path, "todo.md")
    if not os.path.isfile(todo_path):
        return None

    try:
        with open(todo_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("- [ ]"):
                    # Strip the checkbox prefix and return the task text
                    return stripped[5:].strip()
    except OSError:
        pass
    return None


def spawn_claude(project_path: str, task_prompt: str) -> dict:
    """Launch Claude Code in the project directory as a detached background process.

    Returns dict with pid, command, status.
    """
    # Don't spawn if a worker is already running
    if is_claude_running(project_path):
        info = _read_spawn_info(project_path) or {}
        return {
            "pid": info.get("pid"),
            "task": task_prompt,
            "status": "already_running",
            "mode": "subprocess",
        }

    # Build the claude command — use full path for scheduled task context
    claude_exe = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if not os.path.isfile(claude_exe):
        claude_exe = "claude"  # fallback to PATH

    prompt = (
        f"You are a Smart Loops worker. Complete this task from the todo list:\n\n"
        f"**{task_prompt}**\n\n"
        f"When you finish:\n"
        f"1. Check off the task in todo.md: change `- [ ] {task_prompt}` to `- [x] {task_prompt}`\n"
        f"2. Append an entry to .smartloops/claude_log.md in this format:\n"
        f"```\n"
        f"## [current timestamp]\n"
        f"Task: {task_prompt}\n"
        f"Status: completed\n"
        f"Confidence: 90%\n"
        f"Next: [next unchecked todo, or 'All done']\n"
        f"```\n"
        f"3. Commit your changes with a descriptive message\n\n"
        f"Read .smartloops/claude_instructions.md if it exists — it may have recovery instructions from the last cycle."
    )
    cmd = [
        claude_exe,
        "-p", prompt,
        "--output-format", "json",
    ]

    # Log output to .smartloops/worker.log
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    log_path = os.path.join(sl_dir, "worker.log")
    log_file = open(log_path, "w", encoding="utf-8")

    # Detach from current process tree on Windows
    kwargs = {
        "cwd": project_path,
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": log_file,
    }

    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    pid = proc.pid

    _write_spawn_info(project_path, {
        "pid": pid,
        "task": task_prompt,
        "started": _utc_now(),
        "status": "running",
        "mode": "subprocess",
    })

    return {
        "pid": pid,
        "task": task_prompt,
        "status": "spawned",
        "mode": "subprocess",
    }


def is_claude_running(project_path: str) -> bool:
    """Check if a previously spawned Claude process is still alive."""
    info = _read_spawn_info(project_path)
    if not info:
        return False

    pid = info.get("pid")
    if not pid:
        return False

    # Check if PID is still alive
    try:
        if sys.platform == "win32":
            # On Windows, os.kill with signal 0 doesn't work the same way.
            # Use tasklist to check.
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
                stdin=subprocess.DEVNULL,
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, OSError):
        return False


def mark_spawn_complete(project_path: str) -> None:
    """Mark the current spawn as completed (called when Claude finishes)."""
    info = _read_spawn_info(project_path)
    if info:
        info["status"] = "completed"
        info["finished"] = _utc_now()
        _write_spawn_info(project_path, info)


def _spawn_path(project_path: str) -> str:
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    return os.path.join(sl_dir, SPAWN_FILE)


def _read_spawn_info(project_path: str) -> dict | None:
    path = _spawn_path(project_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_spawn_info(project_path: str, data: dict) -> None:
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    with open(_spawn_path(project_path), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _utc_now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()
