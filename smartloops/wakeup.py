"""Smart Loops — Smart wake-up scoring engine.

The core innovation. Calculates when to next wake up based on project state.
"""

import json
import os
from datetime import datetime, timedelta

from config import (
    SMARTLOOPS_DIR, NEXT_WAKEUP_FILE,
    WAKE_SIMPLE, WAKE_LARGE_FEATURE, WAKE_BLOCKED,
    WAKE_HIGH_CONFIDENCE, WAKE_INACTIVE,
)
from smartloops import db, claude_log, git


def calculate_next_wakeup(name: str) -> dict:
    """Calculate next wake-up time for a project.

    Returns dict with: minutes, timestamp, reason, confidence
    """
    project = db.get_project(name)
    if not project:
        return {"error": f"Project '{name}' not found"}

    pid = project["id"]
    path = project["path"]

    # Gather inputs
    log_entries = claude_log.parse_entries(path)
    latest_log = log_entries[-1] if log_entries else None
    latest_audit = db.get_latest_audit(pid)
    wake_history = db.get_wake_history(pid, limit=5)

    confidence = latest_log.get("confidence", 50) if latest_log else 50
    claude_status = (latest_log.get("status") or "unknown").lower() if latest_log else "no_log"

    # --- Scoring ---
    minutes = WAKE_HIGH_CONFIDENCE  # default: 6 hours
    reason = "Default interval"

    # Blocked → wake soon
    if claude_status == "blocked":
        minutes = WAKE_BLOCKED  # 15 min
        reason = "Claude is blocked"
    elif claude_status in ("stuck", "failed"):
        minutes = WAKE_BLOCKED
        reason = f"Claude status: {claude_status}"

    # Low confidence → wake sooner
    elif confidence < 30:
        minutes = WAKE_SIMPLE  # 10 min
        reason = f"Very low confidence ({confidence}%)"
    elif confidence < 50:
        minutes = 30
        reason = f"Low confidence ({confidence}%)"

    # High confidence + active → wake later
    elif confidence >= 80 and claude_status == "in progress":
        # Check if it's a large feature (many log entries about same task)
        if _is_large_feature(log_entries):
            minutes = WAKE_LARGE_FEATURE  # 3 hours
            reason = "Large feature in progress, high confidence"
        else:
            minutes = WAKE_HIGH_CONFIDENCE  # 6 hours
            reason = "Autonomous work, high confidence"

    # No log entries → check if there are pending todos
    elif not log_entries:
        from smartloops.audit import _get_next_task
        next_task = _get_next_task(path)
        if next_task:
            minutes = WAKE_SIMPLE  # 10 min — todos waiting, need to spawn
            reason = f"No activity but todos pending: {next_task[:60]}"
        else:
            minutes = WAKE_INACTIVE  # 24 hours
            reason = "No Claude activity, checking tomorrow"

    # Repeated wake-ups with same result → extend interval
    if len(wake_history) >= 3:
        recent_reasons = [w.get("reason", "") for w in wake_history[-3:]]
        if len(set(recent_reasons)) == 1:
            # Same reason 3 times — extend, but cap if todos still pending
            from smartloops.audit import _get_next_task
            has_todos = _get_next_task(path) is not None
            max_cap = 30 if has_todos else WAKE_INACTIVE
            minutes = min(minutes * 2, max_cap)
            reason += " (extended: repeated pattern)"

    # Risk from audit
    if latest_audit and latest_audit.get("risk_level") == "critical":
        minutes = min(minutes, WAKE_SIMPLE)
        reason = "Critical risk override"
    elif latest_audit and latest_audit.get("risk_level") == "high":
        minutes = min(minutes, 30)

    # Git velocity adjustment
    velocity = git.get_velocity(path)
    if velocity.get("is_repo"):
        commits_day = velocity.get("commits_day", 0)
        trend = velocity.get("velocity_trend", "stable")
        last_commit_age = velocity.get("last_commit_age_hours")

        # High activity + rising trend → project is humming, check less often
        if commits_day >= 3 and trend == "rising":
            minutes = max(minutes, WAKE_HIGH_CONFIDENCE)
            reason = f"Active project ({commits_day}/day, rising) — {reason}"
        # Stale commits + pending todos → wake soon, work needs attention
        elif last_commit_age is not None and last_commit_age > 24:
            from smartloops.audit import _get_next_task
            if _get_next_task(path):
                minutes = min(minutes, WAKE_SIMPLE)
                reason = f"Stale commit ({last_commit_age:.0f}h ago) + pending todos"

    # Calculate timestamp
    next_time = datetime.utcnow() + timedelta(minutes=minutes)
    timestamp = next_time.isoformat()

    result = {
        "project": name,
        "minutes": minutes,
        "timestamp": timestamp,
        "reason": reason,
        "confidence": confidence,
        "claude_status": claude_status,
    }

    # Write next_wakeup.json
    _write_next_wakeup(path, result)

    # Update project in DB
    db.update_project(name, next_wakeup=timestamp)

    # Record this wake decision
    db.add_wake_record(pid, reason=reason, next_wakeup=timestamp)

    return result


def _is_large_feature(log_entries: list[dict]) -> bool:
    """Heuristic: if 3+ entries about the same task, it's a large feature."""
    if len(log_entries) < 3:
        return False
    recent_tasks = [e.get("task", "") for e in log_entries[-3:]]
    # If tasks share significant words, it's probably one big feature
    task_words = [set(t.lower().split()) for t in recent_tasks if t]
    if len(task_words) >= 2:
        overlap = task_words[0] & task_words[1]
        return len(overlap) >= 2
    return False


def _write_next_wakeup(project_path: str, data: dict):
    """Write next_wakeup.json to .smartloops/ dir."""
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    path = os.path.join(sl_dir, NEXT_WAKEUP_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def should_wake_now(name: str) -> bool:
    """Check if it's time to wake up for a project."""
    project = db.get_project(name)
    if not project:
        return False

    next_wakeup = project.get("next_wakeup")
    if not next_wakeup:
        return True  # No schedule = wake up

    try:
        wake_time = datetime.fromisoformat(next_wakeup)
        return datetime.utcnow() >= wake_time
    except (ValueError, TypeError):
        return True
