"""Smart Loops — Project audit engine."""

import os
import json
import subprocess
from datetime import datetime

from config import SMARTLOOPS_DIR, WORLD_MODEL_FILE
from smartloops import db, claude_log, journal, git


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

    # Gather state from all sources
    todo_data = _read_todo(path)
    claude_md = _read_claude_md(path)
    git_data = _read_git_log(path)
    git_velocity = git.get_velocity(path)
    log_entries = claude_log.parse_entries(path)
    ralph_entries = journal.read_entries(path, limit=5)

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
    risk_level = _assess_risk(confidence, claude_status, git_data, log_entries)

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
    }


def _read_todo(project_path: str) -> dict:
    """Parse todo.md for completion stats."""
    todo_path = os.path.join(project_path, "todo.md")
    if not os.path.isfile(todo_path):
        return {"total": 0, "completed": 0}

    with open(todo_path, "r", encoding="utf-8") as f:
        content = f.read()

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
    with open(path, "r", encoding="utf-8") as f:
        return f.read(2000)


def _read_git_log(project_path: str) -> list[str]:
    """Get last 10 git commit subjects."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return []


def _assess_risk(confidence: int, claude_status: str, git_data: list, log_entries: list) -> str:
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

    # Repeated low confidence entries
    if len(log_entries) >= 3:
        recent_confidences = [e.get("confidence", 50) for e in log_entries[-3:]]
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
    sl_dir = os.path.join(project_path, SMARTLOOPS_DIR)
    os.makedirs(sl_dir, exist_ok=True)
    path = os.path.join(sl_dir, WORLD_MODEL_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
