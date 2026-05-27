"""Smart Loops — Git velocity metrics.

Enriches audits with commit frequency, velocity trends, and file change data.
Uses subprocess.run with explicit pipe redirection to avoid MCP stdio deadlocks.
"""

import subprocess
from datetime import datetime, timedelta, timezone


def _git(project_path: str, args: str) -> str:
    """Run a git command and return stdout. Uses subprocess to isolate from MCP transport."""
    try:
        result = subprocess.run(
            ["git", "-C", project_path] + args.split(),
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def get_velocity(project_path: str) -> dict:
    """Get git velocity metrics for a project.

    Returns dict with:
        commits_day, commits_week, velocity_trend (rising/stable/declining),
        files_changed (last 10), last_commit_age_hours, is_repo
    """
    result = {
        "commits_day": 0,
        "commits_week": 0,
        "velocity_trend": "stable",
        "files_changed": [],
        "last_commit_age_hours": None,
        "is_repo": False,
    }

    # Check if it's a git repo
    check = _git(project_path, "rev-parse --is-inside-work-tree")
    if check.strip() != "true":
        return result
    result["is_repo"] = True

    now = datetime.now(timezone.utc)
    day_ago = (now - timedelta(hours=24)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    two_weeks_ago = (now - timedelta(days=14)).isoformat()

    # Commits in last 24 hours
    output = _git(project_path, f"log --oneline --since=\"{day_ago}\"")
    if output:
        result["commits_day"] = len([l for l in output.splitlines() if l.strip()])

    # Commits in last 7 days
    output = _git(project_path, f"log --oneline --since=\"{week_ago}\"")
    if output:
        result["commits_week"] = len([l for l in output.splitlines() if l.strip()])

    # Velocity trend: compare this week vs last week
    output = _git(project_path, f"log --oneline --since=\"{two_weeks_ago}\" --until=\"{week_ago}\"")
    if output:
        prev_week = len([l for l in output.splitlines() if l.strip()])
        this_week = result["commits_week"]
        if this_week > prev_week * 1.2:
            result["velocity_trend"] = "rising"
        elif this_week < prev_week * 0.8:
            result["velocity_trend"] = "declining"
        else:
            result["velocity_trend"] = "stable"

    # Files changed in last 10 commits
    output = _git(project_path, "diff --name-only HEAD~10 HEAD")
    if output:
        result["files_changed"] = [l.strip() for l in output.splitlines() if l.strip()][:20]

    # Age of last commit
    output = _git(project_path, "log -1 --format=%aI")
    if output:
        try:
            last_commit_time = datetime.fromisoformat(output.replace("Z", "+00:00"))
            result["last_commit_age_hours"] = round(
                (now - last_commit_time).total_seconds() / 3600, 1
            )
        except (ValueError, TypeError):
            pass

    return result
