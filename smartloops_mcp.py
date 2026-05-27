"""Smart Loops MCP — Intelligent wake-up scheduler for Claude Code.

Entry point for the MCP server. Uses lazy imports to avoid blocking
the stdio transport during module initialization.
"""

import sys
import os

# Add project root to path so config is importable
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP

# Only import db at top level — it's needed by most tools and only does SQLite init.
# All other modules are imported lazily inside their tool functions.
from smartloops import db

mcp = FastMCP("smartloops")


# --- Project Management ---

@mcp.tool()
def project_register(name: str, path: str, goal: str) -> str:
    """Register a new project for Smart Loops to watch.

    Creates the .smartloops/ directory in the project root.
    """
    existing = db.get_project(name)
    if existing:
        return f"Project '{name}' already registered at {existing['path']}"

    # Resolve path
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return f"Error: path does not exist: {path}"

    # Create .smartloops/ directory
    sl_dir = os.path.join(path, ".smartloops")
    os.makedirs(sl_dir, exist_ok=True)

    # Create empty claude_log.md if not present
    log_path = os.path.join(sl_dir, "claude_log.md")
    if not os.path.isfile(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# Claude Work Log\n")

    # Create empty ralph_journal.md
    journal_path = os.path.join(sl_dir, "ralph_journal.md")
    if not os.path.isfile(journal_path):
        with open(journal_path, "w", encoding="utf-8") as f:
            f.write("# Ralph Journal\n")

    pid = db.add_project(name, path, goal)
    return f"Registered project '{name}' (id={pid}) at {path}\nGoal: {goal}"


@mcp.tool()
def project_list() -> str:
    """List all registered projects with their status."""
    projects = db.list_projects()
    if not projects:
        return "No projects registered."

    lines = []
    for p in projects:
        status_icon = {"active": "●", "paused": "⏸", "complete": "✓"}.get(p["status"], "?")
        last = p.get("last_audit") or "never"
        lines.append(
            f"{status_icon} {p['name']} — {p['status']}\n"
            f"  Path: {p['path']}\n"
            f"  Goal: {p['goal']}\n"
            f"  Last audit: {last}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def project_status(name: str) -> str:
    """Get detailed status for a project including latest audit."""
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."

    lines = [
        f"Project: {project['name']}",
        f"Status: {project['status']}",
        f"Path: {project['path']}",
        f"Goal: {project['goal']}",
        f"Created: {project['created']}",
        f"Last audit: {project.get('last_audit') or 'never'}",
    ]

    # Latest audit
    latest = db.get_latest_audit(project["id"])
    if latest:
        lines.append(f"\nLatest Audit ({latest['timestamp']}):")
        lines.append(f"  Confidence: {latest['confidence']}%")
        lines.append(f"  Risk: {latest['risk_level']}")
        lines.append(f"  Assessment: {latest['assessment']}")

    # Recent wake history
    wakes = db.get_wake_history(project["id"], limit=3)
    if wakes:
        lines.append(f"\nRecent Wake-ups:")
        for w in wakes:
            lines.append(f"  {w['woke_at']} — {w.get('reason', 'no reason')}")

    return "\n".join(lines)


@mcp.tool()
def delete_project(name: str) -> str:
    """Delete a project and all its audit/wake history from Smart Loops."""
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."

    conn = db._get_conn()
    conn.execute("DELETE FROM wake_history WHERE project_id = ?", (project["id"],))
    conn.execute("DELETE FROM audits WHERE project_id = ?", (project["id"],))
    conn.execute("DELETE FROM projects WHERE id = ?", (project["id"],))
    conn.commit()
    conn.close()
    return f"Deleted project '{name}' and all its history."


# --- Audit ---

@mcp.tool()
def audit_project(name: str) -> str:
    """Run a full project audit. Reads todo, CLAUDE.md, git log, Claude's log."""
    from smartloops import audit
    result = audit.audit_project(name)
    if "error" in result:
        return f"Error: {result['error']}"

    lines = [
        f"=== Audit: {result['project']} ===",
        f"Confidence: {result['confidence']}%",
        f"Risk Level: {result['risk_level']}",
        "",
        result["assessment"],
    ]
    if result.get("next_task"):
        lines.append(f"\nNext task: {result['next_task']}")
    return "\n".join(lines)


# --- Claude Log ---

@mcp.tool()
def read_claude_log(name: str, limit: int = 10) -> str:
    """Read Claude's work log for a project."""
    from smartloops import claude_log
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."

    entries = claude_log.parse_entries(project["path"])
    if not entries:
        return "No Claude log entries found."

    # Return last `limit` entries
    entries = entries[-limit:]
    lines = []
    for e in entries:
        lines.append(f"## {e['timestamp']}")
        lines.append(f"  Task: {e['task']}")
        lines.append(f"  Status: {e['status']}")
        lines.append(f"  Confidence: {e['confidence']}%")
        if e.get("next"):
            lines.append(f"  Next: {e['next']}")
        if e.get("issue"):
            lines.append(f"  Issue: {e['issue']}")
        lines.append("")

    return "\n".join(lines)


# --- Ralph Journal ---

@mcp.tool()
def read_ralph_journal(name: str, limit: int = 10) -> str:
    """Read Ralph's observation journal for a project."""
    from smartloops import journal
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."

    entries = journal.read_entries(project["path"], limit=limit)
    if not entries:
        return "No Ralph journal entries found."

    lines = []
    for e in entries:
        lines.append(f"## {e['timestamp']}")
        lines.append(f"  Observed: {e['observed']}")
        lines.append(f"  Action: {e['action']}")
        lines.append(f"  Next Wake: {e['next_wake']}")
        lines.append(f"  Reason: {e['reason']}")
        lines.append("")

    return "\n".join(lines)


# --- Phase 2: Smart Wake-Up ---

@mcp.tool()
def calculate_next_wakeup(name: str) -> str:
    """Calculate the next intelligent wake-up time for a project.

    Scores based on task complexity, confidence, risk, and progress.
    Writes next_wakeup.json to the project's .smartloops/ dir.
    """
    from smartloops import wakeup
    result = wakeup.calculate_next_wakeup(name)
    if "error" in result:
        return f"Error: {result['error']}"

    lines = [
        f"=== Next Wake-up: {result['project']} ===",
        f"Wake in: {result['minutes']} minutes",
        f"Wake at: {result['timestamp']}",
        f"Reason: {result['reason']}",
        f"Confidence: {result['confidence']}%",
        f"Claude status: {result['claude_status']}",
    ]
    return "\n".join(lines)


@mcp.tool()
def detect_stuck(name: str) -> str:
    """Check if a project is stuck. Looks for repeated errors, no commits, low confidence."""
    from smartloops import stuck
    result = stuck.detect_stuck(name)
    if "error" in result:
        return f"Error: {result['error']}"

    if not result["stuck"]:
        return f"Project '{name}' is NOT stuck. No warning signals detected."

    lines = [
        f"=== STUCK DETECTED: {name} ===",
        f"Severity: {result['severity']}",
        f"Signals: {result['signal_count']}",
        "",
    ]
    for s in result["signals"]:
        lines.append(f"  [{s['severity'].upper()}] {s['type']}: {s['detail']}")
    return "\n".join(lines)


@mcp.tool()
def detect_drift(name: str) -> str:
    """Check if a project has drifted from its goal. Compares current work vs registered goal."""
    from smartloops import drift
    result = drift.detect_drift(name)
    if "error" in result:
        return f"Error: {result['error']}"

    if not result.get("drifted"):
        reason = result.get("reason", "")
        if reason:
            return f"Project '{name}': {reason}"
        return (f"Project '{name}' is on track. "
                f"Goal overlap: {result.get('overlap_ratio', 0):.0%}")

    lines = [
        f"=== DRIFT DETECTED: {name} ===",
        f"Goal: {result['goal']}",
        f"Current focus: {result['current_focus']}",
        f"Goal overlap: {result['overlap_ratio']:.0%}",
        f"Matching keywords: {', '.join(result['overlap']) or 'none'}",
        f"Missing keywords: {', '.join(set(result['goal_keywords']) - set(result['overlap'])) or 'none'}",
        "",
        f"Suggestion: {result['suggestion']}",
    ]
    return "\n".join(lines)


# --- Project Lifecycle ---

@mcp.tool()
def pause_project(name: str) -> str:
    """Pause a project — stops wake-ups and audits until resumed."""
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."
    if project["status"] != "active":
        return f"Project '{name}' is already {project['status']}."

    db.update_project(name, status="paused")
    return f"Project '{name}' paused. Wake-ups and audits stopped."


@mcp.tool()
def resume_project(name: str) -> str:
    """Resume a paused project."""
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."
    if project["status"] != "paused":
        return f"Project '{name}' is not paused (status: {project['status']})."

    db.update_project(name, status="active")
    return f"Project '{name}' resumed. Wake-ups will resume on schedule."


@mcp.tool()
def complete_project(name: str) -> str:
    """Mark a project as complete — stops wake-ups, writes final Ralph journal entry."""
    from smartloops import journal
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."
    if project["status"] == "complete":
        return f"Project '{name}' is already complete."

    journal.append_entry(
        project_path=project["path"],
        observed=f"Project completed. Goal: {project['goal']}",
        action="Marked complete — wake-ups stopped",
        next_wake="Never",
        reason="Project complete",
    )

    db.update_project(name, status="complete")
    return f"Project '{name}' marked complete. Final journal entry written."


# --- Notifications ---

@mcp.tool()
def notify_human(name: str, message: str) -> str:
    """Send a Telegram notification about a project. Requires SMARTLOOPS_TELEGRAM_TOKEN and SMARTLOOPS_TELEGRAM_CHAT_ID env vars."""
    from smartloops import notify
    result = notify.send_message(name, message)
    if result["success"]:
        return f"Notification sent for '{name}'."
    return f"Failed to notify: {result['detail']}"


# --- Wake-Up Loop ---

@mcp.tool()
def run_cycle() -> str:
    """Run one wake-up cycle for all active projects. Checks which projects are due and runs audit/stuck/drift on them."""
    from smartloops import loop
    results = loop.run_cycle()
    if not results:
        return "No projects due for wake-up."

    lines = []
    for r in results:
        name = r["project"]
        stuck_info = r.get("stuck", {})
        drift_info = r.get("drift", {})
        wake_info = r.get("wake", {})
        spawn_info = r.get("spawn")

        status_parts = []
        if stuck_info.get("stuck"):
            status_parts.append(f"STUCK({stuck_info['severity']})")
        if drift_info.get("drifted"):
            status_parts.append("DRIFTED")
        if spawn_info:
            status_parts.append(f"SPAWNED(PID {spawn_info['pid']})")
        if not status_parts:
            status_parts.append("OK")

        lines.append(
            f"  {name}: {' | '.join(status_parts)}\n"
            f"    Next wake: {wake_info.get('timestamp', 'unknown')}\n"
            f"    Reason: {wake_info.get('reason', 'ok')}"
        )
        if spawn_info:
            lines.append(f"    Task: {spawn_info['task']}")

    return f"Woke {len(results)} project(s):\n" + "\n".join(lines)


# --- Entry Point ---

if __name__ == "__main__":
    mcp.run()
