"""Smart Loops — Wake-up loop.

The main cycle: check all active projects, wake those whose time has come,
run audit/stuck/drift detection, and schedule next wake-up.
"""

import sys
import os
from datetime import datetime

# Add project root so config is importable when run as `python -m smartloops.loop`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smartloops import db, audit, wakeup, stuck, drift, journal, notify
from smartloops import executor


def run_cycle() -> list[dict]:
    """Run one wake-up cycle across all active projects.

    Returns list of results for projects that were woken up.
    """
    projects = db.list_projects(status="active")
    results = []

    for project in projects:
        name = project["name"]

        # Check if it's time to wake up
        if not wakeup.should_wake_now(name):
            continue

        # Run full check cycle
        result = _check_project(name)
        results.append(result)

    return results


def _check_project(name: str) -> dict:
    """Run the full check cycle for a single project."""
    project = db.get_project(name)
    path = project["path"]

    # 1. Audit
    audit_result = audit.audit_project(name)

    # 2. Stuck detection
    stuck_result = stuck.detect_stuck(name)

    # 3. Drift detection
    drift_result = drift.detect_drift(name)

    # 4. Calculate next wake-up
    wake_result = wakeup.calculate_next_wakeup(name)

    # 5. Build summary for Ralph journal
    observed_parts = []
    if "error" not in audit_result:
        observed_parts.append(
            f"Confidence: {audit_result['confidence']}%, "
            f"Risk: {audit_result['risk_level']}"
        )

    if stuck_result.get("stuck"):
        observed_parts.append(
            f"STUCK ({stuck_result['severity']}): "
            + "; ".join(s["detail"] for s in stuck_result["signals"])
        )

    if drift_result.get("drifted"):
        observed_parts.append(f"DRIFT: {drift_result.get('suggestion', '')}")

    observed = "\n".join(observed_parts) if observed_parts else "No issues detected"

    action = "Scheduled next wake-up"
    notified = False
    spawn_result = None

    if stuck_result.get("stuck") and stuck_result.get("severity") in ("high", "critical"):
        action = "Stuck detected — notifying human"
        notify.send_message(name, f"STUCK ({stuck_result['severity']})\n" + "\n".join(s["detail"] for s in stuck_result["signals"]))
        notified = True
    elif drift_result.get("drifted"):
        action = "Drift detected — review recommended"
        notify.send_message(name, f"DRIFT DETECTED\n{drift_result.get('suggestion', '')}")
        notified = True
    else:
        # 4. Execution — spawn Claude if there's work to do
        next_task = audit_result.get("next_task")
        has_todos = audit_result.get("world_model", {}).get("todo", {}).get("remaining", 0) > 0
        already_running = executor.is_claude_running(path)

        if has_todos and next_task and not already_running and stuck_result.get("severity") not in ("high", "critical"):
            spawn_result = executor.spawn_claude(path, next_task)
            action = f"Spawned Claude (PID {spawn_result['pid']}) to work on: {next_task}"

    # Write Ralph journal entry
    next_wake = wake_result.get("timestamp", "unknown") if "error" not in wake_result else "unknown"
    reason = wake_result.get("reason", "scheduled") if "error" not in wake_result else "error"

    journal.append_entry(
        project_path=path,
        observed=observed,
        action=action,
        next_wake=next_wake,
        reason=reason,
    )

    # Record wake in DB
    db.add_wake_record(
        project_id=project["id"],
        reason=reason,
        action_taken=action,
        next_wakeup=next_wake,
    )

    return {
        "project": name,
        "audit": audit_result,
        "stuck": stuck_result,
        "drift": drift_result,
        "wake": wake_result,
        "spawn": spawn_result,
    }


if __name__ == "__main__":
    results = run_cycle()
    if results:
        for r in results:
            name = r["project"]
            stuck_info = r.get("stuck", {})
            drift_info = r.get("drift", {})
            wake_info = r.get("wake", {})
            print(f"[WAKE] {name}: wake={wake_info.get('reason', 'ok')}, "
                  f"stuck={stuck_info.get('stuck', False)}, "
                  f"drift={drift_info.get('drifted', False)}")
    else:
        print("[IDLE] No projects due for wake-up")
