"""Smart Loops — Project audit engine."""

import os
import json
import subprocess
import time
from datetime import datetime

from config import SMARTLOOPS_DIR, WORLD_MODEL_FILE
from smartloops import db, claude_log, journal, git, github

# Hard cap on audit duration (seconds)
AUDIT_TIMEOUT = 5.0


def audit_project(name: str) -> dict:
    """Run a full project audit.

    Reads todo.md, CLAUDE.md, git log, claude_log, ralph journal.
    Returns assessment dict and writes WORLD_MODEL.json.
    """
    project = db.get_project(name)
    if not project:
        return {"error": f"Project '{name}' not found"}

    path = project["path"]
    if not os.path.isdir(path):
        return {"error": f"Project path does not exist: {path}"}

    # Ensure .smartloops/ dir exists (may have been deleted externally)
    sl_dir = os.path.join(path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)

    t_start = time.monotonic()

    # Gather state from all sources — each can fail independently
    todo_data = _read_todo(path)
    next_task = _get_next_task(path)
    claude_md = _read_claude_md(path)
    git_data = _read_git_log(path)

    # Skip expensive calls if we're already past budget
    elapsed = time.monotonic() - t_start

    try:
        git_velocity = git.get_velocity(path) if elapsed < AUDIT_TIMEOUT else {"is_repo": False, "commits_day": 0, "commits_week": 0, "velocity_trend": "stable"}
    except Exception:
        git_velocity = {"is_repo": False, "commits_day": 0, "commits_week": 0, "velocity_trend": "stable"}

    elapsed = time.monotonic() - t_start
    try:
        github_data = github.get_github_summary(path) if elapsed < AUDIT_TIMEOUT else {"has_github": False}
    except Exception:
        github_data = {"has_github": False}

    try:
        log_entries = claude_log.parse_entries(path)
    except Exception:
        log_entries = []

    try:
        ralph_entries = journal.read_entries(path, limit=5)
    except Exception:
        ralph_entries = []

    latest_log = log_entries[-1] if log_entries else None

    # Build assessment
    completed = todo_data.get("completed", 0)
    total = todo_data.get("total", 0)
    remaining = total - completed

    # Confidence from Claude's latest log
    confidence = latest_log.get("confidence", 50) if latest_log else 50

    # Status from Claude's latest log
    claude_status = latest_log.get("status", "unknown") if latest_log else "no_log"

    # Risk assessment
    risk_level = _assess_risk(confidence, claude_status, git_data, log_entries, github_data)

    # Build assessment text
    assessment_lines = [
        f"Project: {name}",
        f"Todo: {completed}/{total} done ({remaining} remaining)",
        f"Claude status: {claude_status}",
        f"Confidence: {confidence}%",
        f"Risk: {risk_level}",
        f"Commits (last 10): {len(git_data)}",
    ]
    if git_velocity["is_repo"]:
        assessment_lines.append(f"Git velocity: {git_velocity['commits_day']}/day, {git_velocity['commits_week']}/week ({git_velocity['velocity_trend']})")
    if github_data.get("has_github"):
        assessment_lines.append(f"GitHub: {github_data['open_issues_count']} issues, {github_data['open_prs_count']} PRs open")
    if latest_log:
        assessment_lines.append(f"Current task: {latest_log.get('task', 'unknown')}")
        if latest_log.get("issue"):
            assessment_lines.append(f"Issue: {latest_log['issue']}")

    assessment = "\n".join(assessment_lines)

    # Write WORLD_MODEL.json
    world_model = {
        "timestamp": datetime.utcnow().isoformat(),
        "project": name,
        "path": path,
        "goal": project["goal"],
        "status": project["status"],
        "todo": {"completed": completed, "total": total, "remaining": remaining},
        "claude_status": claude_status,
        "confidence": confidence,
        "risk_level": risk_level,
        "latest_task": latest_log.get("task") if latest_log else None,
        "latest_issue": latest_log.get("issue") if latest_log else None,
        "git_commits_recent": len(git_data),
        "last_commit": git_data[0] if git_data else None,
        "git_velocity": git_velocity,
        "github": github_data,
        "next_task": next_task,
    }
    _write_world_model(path, world_model)

    # Store audit in DB
    db.add_audit(
        project_id=project["id"],
        assessment=assessment,
        confidence=confidence,
        risk_level=risk_level,
    )

    return {
        "project": name,
        "assessment": assessment,
        "confidence": confidence,
        "risk_level": risk_level,
        "world_model": world_model,
        "next_task": next_task,
    }


def _read_todo(project_path: str) -> dict:
    """Parse todo.md for completion stats."""
    todo_path = os.path.join(project_path, "todo.md")
    if not os.path.isfile(todo_path):
        return {"total": 0, "completed": 0}

    try:
        with open(todo_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return {"total": 0, "completed": 0}

    total = 0
    completed = 0
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [x]"):
            total += 1
            completed += 1
        elif stripped.startswith("- [ ]"):
            total += 1
    return {"total": total, "completed": completed}


def _read_claude_md(project_path: str) -> str:
    """Read first 2000 chars of CLAUDE.md."""
    path = os.path.join(project_path, "CLAUDE.md")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(2000)
    except OSError:
        return ""


def _read_git_log(project_path: str) -> list[str]:
    """Get last 10 git commit subjects."""
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "log", "--oneline", "-10"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    except (subprocess.TimeoutExpired, OSError):
        pass
    return []


def _assess_risk(confidence: int, claude_status: str, git_data: list, log_entries: list, github_data: dict = None) -> str:
    """Assess project risk level: low, medium, high, critical."""
    score = 0

    # Low confidence = higher risk
    if confidence < 30:
        score += 3
    elif confidence < 50:
        score += 2
    elif confidence < 70:
        score += 1

    # Blocked status
    if claude_status.lower() == "blocked":
        score += 3
    elif claude_status.lower() in ("stuck", "failed"):
        score += 4

    # No recent commits
    if not git_data:
        score += 2

    # Many open issues = potential backlog risk
    if github_data and github_data.get("has_github"):
        if github_data["open_issues_count"] > 20:
            score += 2
        elif github_data["open_issues_count"] > 10:
            score += 1

    # Repeated low confidence entries
    if len(log_entries) >= 3:
        recent_confidences = []
        for e in log_entries[-3:]:
            c = e.get("confidence", 50)
            try:
                recent_confidences.append(int(c))
            except (ValueError, TypeError):
                recent_confidences.append(50)
        if all(c < 40 for c in recent_confidences):
            score += 3

    if score >= 6:
        return "critical"
    elif score >= 4:
        return "high"
    elif score >= 2:
        return "medium"
    return "low"


def _write_world_model(project_path: str, model: dict):
    """Write WORLD_MODEL.json to project's .smartloops/ dir."""
    try:
        sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
        os.makedirs(sl_dir, exist_ok=True)
        path = os.path.join(sl_dir, WORLD_MODEL_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(model, f, indent=2, ensure_ascii=False)
    except OSError:
        pass  # Can't write — disk full, permissions, etc. Don't crash the audit.


def _get_next_task(project_path: str) -> str | None:
    """Return the first unchecked todo item, or None."""
    todo_path = os.path.join(project_path, "todo.md")
    if not os.path.isfile(todo_path):
        return None
    try:
        with open(todo_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("- [ ]"):
                    return stripped[5:].strip()
    except OSError:
        pass
    return None
