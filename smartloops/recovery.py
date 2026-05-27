"""Smart Loops — Recovery system.

Escalating recovery actions for stuck projects:
  Level 1: Instruct Claude to retry  (medium severity)
  Level 2: Instruct Claude to re-plan (high severity)
  Level 3: Notify human via Telegram  (handled by notify.py)
  Level 4: Pause project and alert    (critical severity)
"""

import os
from datetime import datetime

from smartloops import db, notify


def _write_instructions(project_path: str, header: str, body: str) -> dict:
    """Append a recovery instruction to .smartloops/claude_instructions.md."""
    instructions_dir = os.path.join(project_path, ".smartloops")
    os.makedirs(instructions_dir, exist_ok=True)

    instructions_file = os.path.join(instructions_dir, "claude_instructions.md")
    timestamp = datetime.utcnow().isoformat() + "Z"

    entry = (
        f"\n## {header}\n"
        f"**Time**: {timestamp}\n\n"
        f"{body}\n"
    )

    # Append to file (create if missing)
    with open(instructions_file, "a", encoding="utf-8") as f:
        f.write(entry)

    return {"written": True, "file": instructions_file, "header": header}


def instruct_retry(project_path: str, message: str) -> dict:
    """Level 1 — Tell Claude to retry the current task.

    Writes a retry instruction to .smartloops/claude_instructions.md.
    """
    body = (
        f"**Action**: RETRY\n\n"
        f"The previous approach may have hit a transient issue. "
        f"Please retry the current task with a fresh attempt.\n\n"
        f"**Detail**: {message}"
    )
    return _write_instructions(project_path, "RECOVERY Level 1 — Retry", body)


def instruct_replan(project_path: str, message: str) -> dict:
    """Level 2 — Tell Claude to re-plan the approach.

    Writes a re-plan instruction to .smartloops/claude_instructions.md.
    """
    body = (
        f"**Action**: RE-PLAN\n\n"
        f"The current approach is not working. "
        f"Please re-assess the situation, review the project goal and todo list, "
        f"and create a new plan before proceeding.\n\n"
        f"**Detail**: {message}"
    )
    return _write_instructions(project_path, "RECOVERY Level 2 — Re-plan", body)


def notify_human(name: str, message: str) -> dict:
    """Level 3 — Send Telegram alert (delegates to notify.send_message)."""
    return notify.send_message(name, message)


def pause_and_alert(name: str, message: str) -> dict:
    """Level 4 — Pause the project and send Telegram alert.

    Sets project status to 'paused' in the database and notifies the human.
    """
    project = db.get_project(name)
    if not project:
        return {"success": False, "detail": f"Project '{name}' not found"}

    # Pause the project
    db.update_project(name, status="paused")

    # Send Telegram alert
    full_message = (
        f"PROJECT PAUSED\n\n"
        f"{message}\n\n"
        f"The project has been automatically paused. "
        f"Use `resume_project` to continue when ready."
    )
    notify_result = notify.send_message(name, full_message)

    return {
        "success": True,
        "project": name,
        "status": "paused",
        "notified": notify_result.get("success", False),
    }
