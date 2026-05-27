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

    with open(todo_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- [ ]"):
                # Strip the checkbox prefix and return the task text
                return stripped[5:].strip()
    return None


def spawn_claude(project_path: str, task_prompt: str) -> dict:
    """Launch Claude Code in the project directory as a detached background process.

    Only used when running standalone (scheduled task). When called from Claude Code,
    use subagent_spawn() instead — it returns a task description for the Agent tool.

    Returns dict with pid, command, status.
    """
    # Build the claude command — use full path for scheduled task context
    claude_exe = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if not os.path.isfile(claude_exe):
        claude_exe = "claude"  # fallback to PATH
    prompt = f"Work on this task from your todo list: {task_prompt}"
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


def subagent_spawn(project_path: str, task_prompt: str) -> dict:
    """Mark a task as needing a subagent spawn. Returns task info for Claude to use with Agent tool.

    Call this from MCP context — the calling Claude then uses the Agent tool
    to run the task as a visible subagent in the TUI.
    """
    _write_spawn_info(project_path, {
        "pid": None,
        "task": task_prompt,
        "started": _utc_now(),
        "status": "running",
        "mode": "subagent",
    })

    return {
        "task": task_prompt,
        "status": "needs_agent",
        "mode": "subagent",
        "instruction": f"Spawn a subagent to work on: {task_prompt}",
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
