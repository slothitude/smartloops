"""Smart Loops — Executor: spawns Claude Code sessions to work on tasks."""

import json
import os
import subprocess
import sys

from config import SMARTLOOPS_DIR, WORKER_QUESTION_FILE, WORKER_ANSWER_FILE, WORKER_MCP_CONFIG, PTY_ENABLED, PLAN_FILE, WEBTERM_PORT


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


def _get_mcp_config() -> str | None:
    """Return path to worker MCP config, or None if PTY not available.

    PTY_ENABLED modes:
        "auto"  — enable if worker_mcp.json exists (default)
        "true"  — force enable, warn if config missing
        "false" — disabled entirely
    """
    if PTY_ENABLED == "false":
        return None
    if not os.path.isfile(WORKER_MCP_CONFIG):
        if PTY_ENABLED == "true":
            print(f"[smartloops] PTY_ENABLED=true but {WORKER_MCP_CONFIG} not found", file=sys.stderr)
        return None
    try:
        with open(WORKER_MCP_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict) or not servers:
            return None
        return WORKER_MCP_CONFIG
    except (json.JSONDecodeError, OSError):
        return None


def spawn_claude(project_path: str, task_prompt: str, prior_answer: str | None = None) -> dict:
    """Launch Claude Code in the project directory as a detached background process.

    Args:
        project_path: Absolute path to the project root.
        task_prompt: The task description from todo.md.
        prior_answer: Optional human answer to a previous worker question.

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

    # If there's a prior answer, write it to disk so the worker can read it
    if prior_answer:
        _write_worker_answer(project_path, prior_answer)

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
        f"Read .smartloops/claude_instructions.md if it exists — it may have recovery instructions from the last cycle.\n\n"
        f"IMPORTANT: You are running non-interactively (no stdin). Do NOT use AskUserQuestion or any interactive tool.\n"
        f"If you need a human decision, write a JSON file at `.smartloops/{WORKER_QUESTION_FILE}` with:\n"
        f'{{"question": "your question", "choices": ["opt1", "opt2"], "context": "why you need this", "task": "{task_prompt}"}}\n'
        f"Use an empty choices list [] if you need free-text input.\n"
        f"After writing a question, set Status: waiting_for_answer in your claude_log.md entry, then STOP.\n\n"
        f"If `.smartloops/{WORKER_ANSWER_FILE}` exists, read it first — it contains a human response to a previous question."
    )

    if prior_answer:
        prompt += f"\n\nHUMAN RESPONSE TO YOUR PREVIOUS QUESTION:\n{prior_answer}\n\nContinue working with this answer in mind."

    mcp_config = _get_mcp_config()

    # Inject PTY infrastructure section when MCP tools are available
    if mcp_config:
        pty_section = (
            "\n\n## Infrastructure Access\n\n"
            "You have PTY terminal tools. You can SSH into machines and run commands.\n\n"
            "### Machines\n"
            "| Name  | IP             | Use                    |\n"
            "|-------|----------------|------------------------|\n"
            "| Rog   | 192.168.0.52   | This workstation       |\n"
            "| Lappy | 192.168.0.33   | GPU/Docker server      |\n"
            "| Pi    | 192.168.0.237  | Always-on server       |\n\n"
            "### Safety Rules\n"
            "- NEVER: rm -rf /, format, mkfs, dd to disk, shutdown, reboot\n"
            "- NEVER: modify firewall or network config on router (192.168.0.2)\n"
            "- NEVER: disable IP Helper (iphlpsvc) on Rog\n"
            "- ALWAYS prefer read-only first: docker ps, systemctl status, cat, ls\n"
            "- ALWAYS write worker_question.json before: restarting services, deleting data, modifying configs\n"
            "- Log all infrastructure actions in claude_log.md with 'Infra:' prefix\n"
        )
        # Insert PTY section before the IMPORTANT block
        important_marker = "IMPORTANT: You are running non-interactively"
        idx = prompt.find(important_marker)
        if idx != -1:
            prompt = prompt[:idx] + pty_section + "\n" + prompt[idx:]
        else:
            prompt += pty_section

    cmd = [
        claude_exe,
        "-p", prompt,
        "--output-format", "json",
    ]

    # Add MCP config flags when PTY is available
    if mcp_config:
        cmd.extend(["--mcp-config", mcp_config, "--strict-mcp-config"])

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
    log_file.close()  # Release handle in parent; child has its own

    _write_spawn_info(project_path, {
        "pid": pid,
        "task": task_prompt,
        "started": _utc_now(),
        "status": "running",
        "mode": "subprocess",
        "mcp_enabled": bool(mcp_config),
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


# ---------------------------------------------------------------------------
# Planner & Interactive spawning
# ---------------------------------------------------------------------------

def spawn_planner(project_path: str) -> dict:
    """Spawn Claude to create todo.md from an existing plan.md.

    For projects that have plan.md but no todo.md (or all tasks done).
    """
    plan_path = os.path.join(project_path, PLAN_FILE)
    if not os.path.isfile(plan_path):
        return {"error": f"No {PLAN_FILE} found at {project_path}"}

    with open(plan_path, "r", encoding="utf-8", errors="replace") as f:
        plan_content = f.read()

    # Read project goal from DB
    from smartloops import db
    proj = db.get_project_by_path(project_path)
    goal = proj.get("goal", "") if proj else ""

    task_prompt = f"Create todo.md from plan.md"
    prompt = (
        f"You are a Smart Loops planner worker.\n\n"
        f"## Project Goal\n{goal}\n\n"
        f"## plan.md contents\n{plan_content}\n\n"
        f"## Task\n"
        f"Read the plan above and create a `todo.md` file in the project root.\n"
        f"Break the plan into actionable checkbox items: `- [ ] task description`.\n"
        f"Order them by dependency — earlier tasks first.\n"
        f"If a todo.md already exists, merge: keep completed items, add new ones.\n\n"
        f"After creating todo.md, append to .smartloops/claude_log.md:\n"
        f"```\n"
        f"## [{_utc_now()}]\n"
        f"Task: Created todo.md from plan.md\n"
        f"Status: completed\n"
        f"Confidence: 80%\n"
        f"Next: first unchecked todo item\n"
        f"```\n\n"
        f"IMPORTANT: You are running non-interactively. Do NOT use AskUserQuestion or any interactive tool."
    )

    claude_exe = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if not os.path.isfile(claude_exe):
        claude_exe = "claude"

    cmd = [claude_exe, "-p", prompt, "--output-format", "json"]

    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    log_path = os.path.join(sl_dir, "worker.log")

    kwargs = {"cwd": project_path, "stdin": subprocess.DEVNULL,
              "stdout": open(log_path, "w", encoding="utf-8"),
              "stderr": subprocess.STDOUT}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    pid = proc.pid
    kwargs["stdout"].close()

    _write_spawn_info(project_path, {
        "pid": pid,
        "task": task_prompt,
        "started": _utc_now(),
        "status": "running",
        "mode": "planner",
    })

    return {"pid": pid, "task": task_prompt, "status": "spawned", "mode": "planner"}


def spawn_interactive(project_path: str, task_description: str = "Create plan.md and todo.md") -> dict:
    """Start a web terminal for interactive brainstorming.

    Spawns webterm.py as a detached process, sends the URL via Telegram.
    """
    # Find free port
    from webterm import find_free_port
    port = find_free_port(WEBTERM_PORT)

    # Launch webterm.py
    python_exe = sys.executable
    webterm_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webterm.py")

    cmd = [python_exe, webterm_script, "--project-path", project_path, "--port", str(port)]

    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    pid = proc.pid

    url = f"http://100.107.34.12:{port}/"

    _write_spawn_info(project_path, {
        "pid": pid,
        "task": task_description,
        "started": _utc_now(),
        "status": "running",
        "mode": "interactive",
        "url": url,
        "port": port,
    })

    # Notify via Telegram
    try:
        from smartloops import notify
        proj_name = os.path.basename(project_path)
        notify.send_message(proj_name,
                            f"Interactive terminal ready\n"
                            f"Project: {proj_name}\n"
                            f"Task: {task_description}\n"
                            f"URL: {url}")
    except Exception:
        pass  # Notification failure is non-fatal

    return {"pid": pid, "url": url, "status": "spawned_interactive",
            "port": port, "mode": "interactive"}


# ---------------------------------------------------------------------------
# Worker question / answer helpers
# ---------------------------------------------------------------------------

def read_worker_question(project_path: str) -> dict | None:
    """Read and return worker_question.json, or None if not present."""
    path = os.path.join(project_path, SMARTLOOPS_DIR, WORKER_QUESTION_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def clear_worker_question(project_path: str) -> None:
    """Remove worker_question.json after it's been relayed to Telegram."""
    path = os.path.join(project_path, SMARTLOOPS_DIR, WORKER_QUESTION_FILE)
    if os.path.isfile(path):
        os.remove(path)


def clear_worker_answer(project_path: str) -> None:
    """Remove worker_answer.json."""
    path = os.path.join(project_path, SMARTLOOPS_DIR, WORKER_ANSWER_FILE)
    if os.path.isfile(path):
        os.remove(path)


def _write_worker_answer(project_path: str, answer: str) -> None:
    """Write worker_answer.json with the human's response."""
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    path = os.path.join(sl_dir, WORKER_ANSWER_FILE)
    data = {"answer": answer, "timestamp": _utc_now()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def kill_worker(project_path: str) -> bool:
    """Kill the running Claude worker process. Returns True if killed."""
    info = _read_spawn_info(project_path)
    if not info:
        return False
    pid = info.get("pid")
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=5,
                stdin=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, 9)
        info["status"] = "killed"
        _write_spawn_info(project_path, info)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
