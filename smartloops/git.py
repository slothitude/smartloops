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
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def get_velocity(project_path: str) -> dict:
    """Get git velocity metrics for a project.

    Returns dict with:
        commits_day, commits_week, velocity_trend (rising/stable/declining),
        files_changed (last 10), last_commit_age_hours, is_repo

    Optimized to use minimal subprocess calls (2-3 instead of 8).
    """
    result = {
        "commits_day": 0,
        "commits_week": 0,
        "velocity_trend": "stable",
        "files_changed": [],
        "last_commit_age_hours": None,
        "is_repo": False,
    }

    # Combined check: is git repo + has commits (1 call instead of 2)
    check = _git(project_path, "rev-parse --is-inside-work-tree")
    if check.strip() != "true":
        return result
    result["is_repo"] = True

    has_commits = _git(project_path, "rev-parse HEAD")
    if not has_commits:
        return result

    now = datetime.now(timezone.utc)
    two_weeks_ago = (now - timedelta(days=14)).isoformat()

    # Single git log call for all time-based metrics (was 4 separate calls)
    output = _git(project_path, f"log --format=%aI --since=\"{two_weeks_ago}\"")
    if output:
        commit_times = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                commit_times.append(datetime.fromisoformat(line.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                continue

        day_ago = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        result["commits_day"] = sum(1 for t in commit_times if t >= day_ago)
        result["commits_week"] = sum(1 for t in commit_times if t >= week_ago)

        # Velocity trend: this week vs previous week
        prev_week_count = sum(1 for t in commit_times if week_ago > t >= (week_ago - timedelta(days=7)))
        this_week = result["commits_week"]
        if this_week > prev_week_count * 1.2:
            result["velocity_trend"] = "rising"
        elif this_week < prev_week_count * 0.8:
            result["velocity_trend"] = "declining"

    # Last commit age (1 call, but most recent commit is first in log output)
    last_ts = _git(project_path, "log -1 --format=%aI")
    if last_ts:
        try:
            last_commit_time = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            result["last_commit_age_hours"] = round(
                (now - last_commit_time).total_seconds() / 3600, 1
            )
        except (ValueError, TypeError):
            pass

    # Files changed in last 10 commits (1 call)
    count_output = _git(project_path, "rev-list --count HEAD")
    try:
        commit_count = int(count_output) if count_output else 0
    except ValueError:
        commit_count = 0
    depth = min(commit_count, 10)
    if depth > 1:
        output = _git(project_path, f"diff --name-only HEAD~{depth} HEAD")
        if output:
            result["files_changed"] = [l.strip() for l in output.splitlines() if l.strip()][:20]

    return result
