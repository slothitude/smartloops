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
from smartloops import executor, recovery
from config import TELEGRAM_CHAT_ID


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

        # Run full check cycle — one bad project shouldn't stop others
        try:
            result = _check_project(name)
            results.append(result)
        except Exception as e:
            results.append({"project": name, "error": f"Cycle failed: {e}"})

    # Poll Telegram commands and question responses
    try:
        from smartloops import bot
        if bot.is_configured():
            messages, callbacks = bot.poll()
            if messages or callbacks:
                bot.process_commands(messages, callbacks)
            if callbacks:
                responses = bot.check_responses(callbacks)
                for resp in responses:
                    _handle_question_response(resp)
            # Check free-text replies for open-ended questions
            if messages:
                text_responses = bot.check_text_replies(messages)
                for resp in text_responses:
                    _handle_question_response(resp)
    except Exception:
        pass  # Bot failure must not break the cycle

    return results


def _handle_question_response(resp: dict):
    """Act on a user's answer to a pending question."""
    from smartloops import db
    project = resp["project"]
    answer = resp["answer"]
    context = resp.get("context", "")

    # Edit the question message to show the answer
    chat_id = resp.get("chat_id")
    message_id = resp.get("message_id")
    if chat_id and message_id:
        try:
            from smartloops import bot
            bot.edit_message(chat_id, message_id,
                             f"Question #{resp['id']} for *{project}*:\n"
                             f"~~{resp['question']}~~\n\n"
                             f"Answer: *{answer}*")
        except Exception:
            pass

    if context == "drift_detected":
        if answer in ("re-plan", "yes"):
            proj = db.get_project(project)
            if proj:
                from smartloops import recovery
                recovery.instruct_replan(proj["path"], "User confirmed re-plan via Telegram")
        elif answer in ("pause", "no"):
            db.update_project(project, status="paused")

    elif context == "stuck_critical":
        if answer in ("resume", "yes"):
            db.update_project(project, status="active")
        elif answer in ("pause", "no"):
            db.update_project(project, status="paused")

    elif context == "recovery":
        if answer == "re-plan":
            proj = db.get_project(project)
            if proj:
                from smartloops import recovery
                recovery.instruct_replan(proj["path"], "User requested re-plan via Telegram")
        elif answer == "pause":
            db.update_project(project, status="paused")
        # "ignore" — do nothing

    elif context.startswith("worker_question:"):
        # Extract project name from context tag
        proj = db.get_project(project)
        if proj:
            path = proj["path"]
            # Kill the old worker if still running
            if executor.is_claude_running(path):
                executor.kill_worker(path)
            # Clear any stale answer file
            executor.clear_worker_answer(path)
            # Re-spawn with the human's answer injected
            # Read the original task from the question context or spawn info
            spawn_info = executor._read_spawn_info(path)
            task = spawn_info.get("task", "Continue previous task") if spawn_info else "Continue previous task"
            executor.spawn_claude(path, task, prior_answer=answer)

    # Acknowledge the response
    from smartloops import bot
    bot.send_reply(
        str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else "",
        f"Received: {answer} for {project} (Q#{resp['id']})",
    )


def _check_project(name: str) -> dict:
    """Run the full check cycle for a single project."""
    project = db.get_project(name)
    path = project["path"]

    # 1. Audit
    try:
        audit_result = audit.audit_project(name)
    except Exception as e:
        audit_result = {"error": f"Audit failed: {e}"}

    # 2. Stuck detection
    try:
        stuck_result = stuck.detect_stuck(name)
    except Exception as e:
        stuck_result = {"error": f"Stuck detection failed: {e}", "stuck": False, "signals": [], "severity": "none"}

    # 3. Drift detection
    try:
        drift_result = drift.detect_drift(name)
    except Exception as e:
        drift_result = {"error": f"Drift detection failed: {e}", "drifted": False, "suggestion": ""}

    # 4. Calculate next wake-up
    try:
        wake_result = wakeup.calculate_next_wakeup(name)
    except Exception as e:
        wake_result = {"error": f"Wake-up calc failed: {e}", "minutes": 30, "timestamp": "unknown", "reason": "error"}

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

    if stuck_result.get("stuck"):
        severity = stuck_result.get("severity", "low")
        stuck_details = "\n".join(s["detail"] for s in stuck_result.get("signals", []))

        if severity == "critical":
            # Level 4: pause project and alert human
            recovery_result = recovery.pause_and_alert(name, stuck_details)
            action = f"STUCK ({severity}) — paused project, alerted human"
            notified = True
        elif severity == "high":
            # Level 2: instruct Claude to re-plan
            recovery.instruct_replan(path, stuck_details)
            # Level 3: notify human
            recovery.notify_human(name, f"STUCK ({severity})\n{stuck_details}")
            action = f"STUCK ({severity}) — re-plan instructed, human notified"
            notified = True
        elif severity == "medium":
            # Level 1: instruct Claude to retry
            recovery.instruct_retry(path, stuck_details)
            action = f"STUCK ({severity}) — retry instructed"
            # Medium-stuck still gets spawned — spawning IS the fix
            next_task = audit_result.get("next_task")
            has_todos = audit_result.get("world_model", {}).get("todo", {}).get("remaining", 0) > 0
            already_running = executor.is_claude_running(path)
            if has_todos and next_task and not already_running:
                spawn_result = executor.spawn_claude(path, next_task)
                action += f" + SPAWNED: {next_task}"
        else:
            # low severity — just log
            action = f"STUCK ({severity}) — monitoring"
    elif drift_result.get("drifted"):
        action = "Drift detected — review recommended"
        notify.send_message(name, f"DRIFT DETECTED\n{drift_result.get('suggestion', '')}")
        notified = True
    else:
        # 4. Execution — spawn subprocess to work on next todo
        next_task = audit_result.get("next_task")
        has_todos = audit_result.get("world_model", {}).get("todo", {}).get("remaining", 0) > 0
        already_running = executor.is_claude_running(path)

        if has_todos and next_task and not already_running:
            spawn_result = executor.spawn_claude(path, next_task)
            action = f"SPAWNED: {next_task}"
        elif not has_todos and not already_running:
            from config import PLAN_FILE
            plan_path = os.path.join(path, PLAN_FILE)
            if os.path.isfile(plan_path):
                spawn_result = executor.spawn_planner(path)
                action = f"PLANNER: {spawn_result.get('task', '?')}"
            else:
                spawn_result = executor.spawn_interactive(path, "Create plan.md and todo.md")
                action = f"INTERACTIVE: {spawn_result.get('url', '?')}"

    # 5b. Check for worker question (worker needs human input)
    worker_q = executor.read_worker_question(path)
    if worker_q:
        try:
            from smartloops import bot
            if bot.is_configured():
                choices = worker_q.get("choices", [])
                bot.ask_question(
                    project=name,
                    question=worker_q.get("question", "Worker needs input"),
                    choices=choices,
                    context=f"worker_question:{name}",
                )
                executor.clear_worker_question(path)
                action = "WORKER QUESTION sent to Telegram"
        except Exception:
            pass  # Bot failure — question stays on disk for next cycle

    # Write Ralph journal entry
    next_wake = wake_result.get("timestamp", "unknown") if "error" not in wake_result else "unknown"
    reason = wake_result.get("reason", "scheduled") if "error" not in wake_result else "error"

    try:
        journal.append_entry(
            project_path=path,
            observed=observed,
            action=action,
            next_wake=next_wake,
            reason=reason,
        )
    except Exception:
        pass  # Disk error — don't lose the cycle result

    # Record wake in DB
    try:
        db.add_wake_record(
            project_id=project["id"],
            reason=reason,
            action_taken=action,
            next_wakeup=next_wake,
        )
    except Exception:
        pass  # DB error — still return results

    return {
        "project": name,
        "audit": audit_result,
        "stuck": stuck_result,
        "drift": drift_result,
        "wake": wake_result,
        "spawn": spawn_result,
    }


def generate_status_report(name: str) -> str:
    """Generate a comprehensive text status report for a project.

    Runs audit, stuck detection, drift detection, and calculates next wakeup,
    then composes everything into a human-readable report.
    """
    project = db.get_project(name)
    if not project:
        return f"Project '{name}' not found."

    # 1. Audit
    audit_result = audit.audit_project(name)
    if "error" in audit_result:
        return f"Error: {audit_result['error']}"

    # 2. Stuck detection
    stuck_result = stuck.detect_stuck(name)
    if "error" in stuck_result:
        stuck_result = {"stuck": False, "signals": [], "severity": "none"}

    # 3. Drift detection
    drift_result = drift.detect_drift(name)
    if "error" in drift_result:
        drift_result = {"drifted": False, "suggestion": ""}

    # 4. Next wake-up
    wake_result = wakeup.calculate_next_wakeup(name)
    if "error" in wake_result:
        wake_result = {"minutes": 0, "timestamp": "unknown", "reason": "error"}

    # Build the report
    wm = audit_result.get("world_model", {})
    todo = wm.get("todo", {})
    git_vel = wm.get("git_velocity", {})

    lines = [
        f"=== Status Report: {name} ===",
        "",
        "--- Overview ---",
        f"Status:    {project['status']}",
        f"Goal:      {project['goal']}",
        f"Path:      {project['path']}",
        "",
        "--- Todo Progress ---",
        f"Completed: {todo.get('completed', 0)}/{todo.get('total', 0)} ({todo.get('remaining', 0)} remaining)",
    ]

    next_task = audit_result.get("next_task")
    if next_task:
        lines.append(f"Next task:  {next_task}")

    lines += [
        "",
        "--- Assessment ---",
        f"Confidence: {audit_result['confidence']}%",
        f"Risk level: {audit_result['risk_level'].upper()}",
        f"Claude status: {wm.get('claude_status', 'unknown')}",
    ]

    latest_task = wm.get("latest_task")
    if latest_task:
        lines.append(f"Current task: {latest_task}")
    latest_issue = wm.get("latest_issue")
    if latest_issue:
        lines.append(f"Current issue: {latest_issue}")

    lines += [
        "",
        "--- Git Velocity ---",
    ]
    if git_vel.get("is_repo"):
        lines.append(f"Commits:  {git_vel.get('commits_day', 0)}/day, {git_vel.get('commits_week', 0)}/week")
        lines.append(f"Trend:    {git_vel.get('velocity_trend', 'stable')}")
        age = git_vel.get("last_commit_age_hours")
        if age is not None:
            if age < 1:
                age_str = f"{age * 60:.0f} minutes ago"
            else:
                age_str = f"{age:.1f} hours ago"
            lines.append(f"Last commit: {age_str}")
    else:
        lines.append("Not a git repository")

    lines += [
        "",
        "--- Stuck Detection ---",
    ]
    if stuck_result.get("stuck"):
        lines.append(f"STUCK ({stuck_result['severity'].upper()}) -- {stuck_result.get('signal_count', 0)} signal(s)")
        for s in stuck_result.get("signals", []):
            lines.append(f"  [{s['severity'].upper()}] {s['type']}: {s['detail']}")
    else:
        lines.append("No stuck signals detected.")

    lines += [
        "",
        "--- Drift Detection ---",
    ]
    if drift_result.get("drifted"):
        lines.append(f"DRIFTED -- goal overlap: {drift_result.get('overlap_ratio', 0):.0%}")
        lines.append(f"Goal:           {drift_result.get('goal', '')}")
        lines.append(f"Current focus:  {drift_result.get('current_focus', '')}")
        if drift_result.get("suggestion"):
            lines.append(f"Suggestion:     {drift_result['suggestion']}")
    else:
        reason = drift_result.get("reason", "")
        if reason:
            lines.append(f"On track. {reason}")
        else:
            lines.append(f"On track. Goal overlap: {drift_result.get('overlap_ratio', 0):.0%}")

    lines += [
        "",
        "--- Next Wake-up ---",
        f"Wake in:   {wake_result.get('minutes', 0)} minutes",
        f"Wake at:   {wake_result.get('timestamp', 'unknown')}",
        f"Reason:    {wake_result.get('reason', 'scheduled')}",
    ]

    return "\n".join(lines)


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
