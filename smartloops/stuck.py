"""Smart Loops — Stuck detection.

Detects stalled progress from log patterns, commit gaps, and low confidence.
"""

from datetime import datetime, timedelta

from config import STUCK_NO_COMMIT_HOURS, STUCK_LOW_CONFIDENCE, STUCK_MAX_REPEATS
from smartloops import db, claude_log


def detect_stuck(name: str) -> dict:
    """Check if a project is stuck.

    Returns dict with: stuck (bool), signals (list), severity (low/medium/high/critical)
    """
    project = db.get_project(name)
    if not project:
        return {"error": f"Project '{name}' not found"}

    path = project["path"]
    signals = []

    # 1. Check Claude log for blocked/stuck/failed status
    log_entries = claude_log.parse_entries(path)
    latest = log_entries[-1] if log_entries else None

    if latest:
        status = (latest.get("status") or "").lower()
        if status in ("blocked", "stuck", "failed"):
            signals.append({
                "type": "status",
                "detail": f"Claude status is '{status}'",
                "severity": "high",
            })

    # 2. Low confidence
    if latest and latest.get("confidence", 100) < STUCK_LOW_CONFIDENCE:
        signals.append({
            "type": "confidence",
            "detail": f"Confidence at {latest['confidence']}% (threshold: {STUCK_LOW_CONFIDENCE}%)",
            "severity": "medium" if latest["confidence"] > 25 else "high",
        })

    # 3. Repeated identical log entries
    if len(log_entries) >= STUCK_MAX_REPEATS:
        recent_tasks = [e.get("task", "") for e in log_entries[-STUCK_MAX_REPEATS:]]
        if len(set(recent_tasks)) == 1:
            signals.append({
                "type": "repetition",
                "detail": f"Same task repeated {STUCK_MAX_REPEATS}+ times: '{recent_tasks[0]}'",
                "severity": "high",
            })

    # 4. Repeated errors — same issue appearing multiple times
    issues = [e.get("issue", "") for e in log_entries if e.get("issue")]
    if len(issues) >= 2:
        unique_issues = set(issues)
        for issue in unique_issues:
            count = issues.count(issue)
            if count >= 2:
                signals.append({
                    "type": "repeated_error",
                    "detail": f"Same issue appeared {count} times: '{issue[:80]}'",
                    "severity": "medium" if count == 2 else "high",
                })

    # 5. No git commits recently
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", path, "log", "-1", "--format=%aI"],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        output = result.stdout.strip()
        if output:
            last_commit_time = datetime.fromisoformat(output.replace("Z", "+00:00"))
            hours_since = (datetime.now(last_commit_time.tzinfo) - last_commit_time).total_seconds() / 3600
            if hours_since > STUCK_NO_COMMIT_HOURS:
                signals.append({
                    "type": "no_commits",
                    "detail": f"No commits for {hours_since:.0f} hours (threshold: {STUCK_NO_COMMIT_HOURS}h)",
                    "severity": "medium" if hours_since < STUCK_NO_COMMIT_HOURS * 2 else "high",
                })
    except Exception:
        pass  # Not a git repo or git unavailable

    # 6. Long-running task with no progress
    if len(log_entries) >= 2:
        first_recent = log_entries[-2]
        last_recent = log_entries[-1]
        if (first_recent.get("task") == last_recent.get("task") and
                first_recent.get("next") == last_recent.get("next")):
            signals.append({
                "type": "no_progress",
                "detail": f"Task '{last_recent.get('task')}' has same 'next' step across entries",
                "severity": "low",
            })

    # Determine overall stuck status and severity
    stuck = len(signals) > 0
    if not stuck:
        return {"stuck": False, "signals": [], "severity": "none"}

    severities = [s["severity"] for s in signals]
    if "high" in severities and len(signals) >= 2:
        overall = "critical"
    elif "high" in severities:
        overall = "high"
    elif "medium" in severities:
        overall = "medium"
    else:
        overall = "low"

    return {
        "stuck": True,
        "signals": signals,
        "severity": overall,
        "signal_count": len(signals),
    }
