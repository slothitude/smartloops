"""Smart Loops — Git velocity metrics.

Enriches audits with commit frequency, velocity trends, and file change data.
"""

import subprocess
from datetime import datetime, timedelta


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

    now = datetime.utcnow()
    day_ago = (now - timedelta(hours=24)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    two_weeks_ago = (now - timedelta(days=14)).isoformat()

    try:
        # Check if it's a git repo
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if check.returncode != 0:
            return result
        result["is_repo"] = True

        # Commits in last 24 hours
        r = subprocess.run(
            ["git", "log", "--oneline", f"--since={day_ago}"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
            result["commits_day"] = len(lines)

        # Commits in last 7 days
        r = subprocess.run(
            ["git", "log", "--oneline", f"--since={week_ago}"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
            result["commits_week"] = len(lines)

        # Velocity trend: compare this week vs last week
        r = subprocess.run(
            ["git", "log", "--oneline", f"--since={two_weeks_ago}", f"--until={week_ago}"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            prev_week = len([l for l in r.stdout.strip().splitlines() if l.strip()])
            this_week = result["commits_week"]
            if this_week > prev_week * 1.2:
                result["velocity_trend"] = "rising"
            elif this_week < prev_week * 0.8:
                result["velocity_trend"] = "declining"
            else:
                result["velocity_trend"] = "stable"

        # Files changed in last 10 commits
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~10", "HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            result["files_changed"] = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()][:20]

        # Age of last commit
        r = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            cwd=project_path, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            try:
                last_commit_time = datetime.fromisoformat(r.stdout.strip().replace("Z", "+00:00"))
                result["last_commit_age_hours"] = round(
                    (now.replace(tzinfo=last_commit_time.tzinfo) - last_commit_time).total_seconds() / 3600, 1
                )
            except (ValueError, TypeError):
                pass

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return result
