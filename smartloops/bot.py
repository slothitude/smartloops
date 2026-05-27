"""Smart Loops — Telegram bot for remote control and interactive alerts.

Polls Telegram for commands once per loop cycle (no threads, no webhooks).
Manages interactive questions via inline buttons.
Uses stdlib urllib only — no extra dependencies.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BOT_STATE_FILE, PENDING_QUESTIONS_FILE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """Check if Telegram bot token and chat ID are set."""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def _api_call(method: str, payload: dict) -> dict | None:
    """Make a Telegram Bot API call, return parsed result or None."""
    url = _api_url(method)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body if body.get("ok") else None
    except Exception:
        return None


def _read_json(path: str, default=None):
    if not os.path.isfile(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def _write_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def poll() -> tuple[list[dict], list[dict]]:
    """Fetch new Telegram updates via long-polling (30s timeout).

    Returns (messages, callbacks):
      - messages:  [{"update_id", "chat_id", "text"}]
      - callbacks: [{"update_id", "chat_id", "data", "message_id"}]

    Only updates from TELEGRAM_CHAT_ID are returned; others consumed silently.
    """
    state = _read_json(BOT_STATE_FILE, {"last_update_id": 0})
    offset = state["last_update_id"] + 1

    url = f"{_api_url('getUpdates')}?offset={offset}&timeout=30&allowed_updates=[\"message\",\"callback_query\"]"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=35) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return [], []

    if not body.get("ok"):
        return [], []

    messages = []
    callbacks = []
    max_id = state["last_update_id"]

    for update in body.get("result", []):
        uid = update.get("update_id", 0)
        if uid > max_id:
            max_id = uid

        # Text messages
        msg = update.get("message") or update.get("edited_message")
        if msg:
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "").strip()
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue
            entry = {
                "update_id": uid,
                "chat_id": chat_id,
                "text": text,
            }
            # Capture reply_to_message for matching free-text answers
            reply_to = msg.get("reply_to_message")
            if reply_to:
                entry["reply_to_message_id"] = reply_to.get("message_id")
            messages.append(entry)
            continue

        # Inline button callbacks
        cb = update.get("callback_query")
        if cb:
            chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if chat_id != str(TELEGRAM_CHAT_ID):
                continue
            callbacks.append({
                "update_id": uid,
                "chat_id": chat_id,
                "data": cb.get("data", ""),
                "message_id": cb.get("message", {}).get("message_id"),
                "callback_query_id": cb.get("id", ""),
            })

    _write_json(BOT_STATE_FILE, {"last_update_id": max_id})
    return messages, callbacks


def answer_callback(callback_query_id: str, text: str = "") -> bool:
    """Acknowledge a callback query (stops the loading spinner on the button)."""
    result = _api_call("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
    })
    return result is not None


def edit_message(chat_id: str, message_id: int, text: str) -> bool:
    """Edit an existing message (e.g. to show which button was selected)."""
    result = _api_call("editMessageText", {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
    })
    return result is not None


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_reply(chat_id: str, text: str, buttons: list[dict] | None = None) -> bool:
    """Send a message, auto-splitting at Telegram's 4096-char limit.

    buttons: optional list of {"text": str, "data": str} for inline keyboard.
    Only the last chunk gets buttons (if any).
    """
    if not TELEGRAM_BOT_TOKEN:
        return False

    chunks = []
    while text:
        chunks.append(text[:4096])
        text = text[4096:]

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        # Attach buttons to the last chunk only
        if buttons and i == len(chunks) - 1:
            row = [{"text": b["text"], "callback_data": b["data"]} for b in buttons]
            payload["reply_markup"] = {"inline_keyboard": [row]}

        result = _api_call("sendMessage", payload)
        if result is None:
            return False

    return True


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "*Smart Loops Bot*\n\n"
    "Commands:\n"
    "/list - Show all projects\n"
    "/status <name> - Full status report\n"
    "/audit <name> - Run audit\n"
    "/stuck <name> - Stuck detection\n"
    "/drift <name> - Drift detection\n"
    "/pause <name> - Pause a project\n"
    "/resume <name> - Resume a project\n"
    "/cycle - Run one wake-up cycle\n"
    "/worker <name> - Worker status\n"
    "/log <name> [N] - Claude log (last N entries)\n"
    "/questions - List pending questions\n"
    "/start - Show this help\n"
    "/help - Show this help"
)


def process_commands(messages: list[dict], callbacks: list[dict] | None = None) -> list[dict]:
    """Parse commands from messages, execute, send replies.
    Also handles button callbacks for question responses.

    Returns list of {"command", "args", "result"} dicts.
    """
    results = []

    # Handle button callbacks first
    if callbacks:
        for cb in callbacks:
            answer_callback(cb["callback_query_id"])
            data = cb.get("data", "")
            if data.startswith("q:"):
                results.append({
                    "command": "callback",
                    "args": [data],
                    "result": f"callback: {data}",
                })

    for msg in messages:
        text = msg["text"]
        chat_id = msg["chat_id"]

        if not text.startswith("/"):
            continue

        parts = text.split(None, 2)
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        try:
            result = _dispatch(cmd, args)
        except Exception as e:
            result = f"Error: {e}"

        reply = str(result) if result else "Done."
        send_reply(chat_id, reply)

        results.append({
            "command": cmd,
            "args": args,
            "result": reply[:200],
        })

    return results


def _dispatch(cmd: str, args: list[str]) -> str:
    """Route a command to the appropriate smartloops function."""
    from smartloops import db

    if cmd in ("/start", "/help"):
        return _HELP_TEXT

    if cmd == "/list":
        projects = db.list_projects()
        if not projects:
            return "No projects registered."
        lines = ["*Projects:*"]
        for p in projects:
            lines.append(f"  {p['status'].upper():8s} {p['name']} — {p['goal'][:60]}")
        return "\n".join(lines)

    if cmd == "/cycle":
        from smartloops.loop import run_cycle
        results = run_cycle()
        if not results:
            return "Cycle complete. No projects due for wake-up."
        lines = []
        for r in results:
            name = r.get("project", "?")
            if "error" in r:
                lines.append(f"{name}: ERROR — {r['error']}")
            else:
                stuck = r.get("stuck", {}).get("stuck", False)
                drifted = r.get("drift", {}).get("drifted", False)
                spawn = r.get("spawn")
                parts = [name]
                if stuck:
                    parts.append("STUCK")
                if drifted:
                    parts.append("DRIFTED")
                if spawn:
                    parts.append(f"spawned(PID {spawn.get('pid', '?')})")
                if not stuck and not drifted and not spawn:
                    parts.append("ok")
                lines.append(" | ".join(parts))
        return "\n".join(lines)

    if not args:
        return "Usage: /{cmd} <project-name>"

    name = args[0]

    if cmd == "/status":
        from smartloops.loop import generate_status_report
        return generate_status_report(name)

    if cmd == "/audit":
        from smartloops.audit import audit_project
        result = audit_project(name)
        if "error" in result:
            return f"Error: {result['error']}"
        return (
            f"Audit: {name}\n"
            f"Confidence: {result.get('confidence', '?')}%\n"
            f"Risk: {result.get('risk_level', '?')}\n"
            f"Next task: {result.get('next_task', 'none')}"
        )

    if cmd == "/stuck":
        from smartloops.stuck import detect_stuck
        result = detect_stuck(name)
        if "error" in result:
            return f"Error: {result['error']}"
        if not result.get("stuck"):
            return f"{name}: Not stuck. ({result.get('severity', 'none')})"
        signals = result.get("signals", [])
        lines = [f"*{name}: STUCK ({result['severity']})*"]
        for s in signals:
            lines.append(f"  [{s['severity']}] {s['type']}: {s['detail']}")
        return "\n".join(lines)

    if cmd == "/drift":
        from smartloops.drift import detect_drift
        result = detect_drift(name)
        if "error" in result:
            return f"Error: {result['error']}"
        if not result.get("drifted"):
            return f"{name}: On track. Overlap: {result.get('overlap_ratio', 0):.0%}"
        return (
            f"*{name}: DRIFTED*\n"
            f"Overlap: {result.get('overlap_ratio', 0):.0%}\n"
            f"Goal: {result.get('goal', '')}\n"
            f"Focus: {result.get('current_focus', '')}\n"
            f"Suggestion: {result.get('suggestion', '')}"
        )

    if cmd == "/pause":
        ok = db.update_project(name, status="paused")
        if not ok:
            return f"Project '{name}' not found."
        return f"Paused: {name}"

    if cmd == "/resume":
        ok = db.update_project(name, status="active")
        if not ok:
            return f"Project '{name}' not found."
        return f"Resumed: {name}"

    if cmd == "/worker":
        project = db.get_project(name)
        if not project:
            return f"Project '{name}' not found."
        from smartloops.executor import is_claude_running, _read_spawn_info
        path = project["path"]
        running = is_claude_running(path)
        info = _read_spawn_info(path)
        if not info:
            return f"{name}: No worker on record."
        return (
            f"*Worker: {name}*\n"
            f"PID: {info.get('pid', '?')}\n"
            f"Task: {info.get('task', '?')}\n"
            f"Status: {info.get('status', '?')}\n"
            f"Alive: {'yes' if running else 'no'}\n"
            f"Started: {info.get('started', '?')}"
        )

    if cmd == "/log":
        n = 5
        if len(args) > 1:
            try:
                n = int(args[1])
            except ValueError:
                pass
        project = db.get_project(name)
        if not project:
            return f"Project '{name}' not found."
        from smartloops.claude_log import parse_entries
        entries = parse_entries(project["path"])
        if not entries:
            return f"{name}: No log entries."
        lines = [f"*Log: {name}* (last {n})"]
        for entry in entries[:n]:
            lines.append(
                f"  [{entry.get('timestamp', '?')[:16]}] "
                f"{entry.get('task', '?')[:50]} — "
                f"{entry.get('status', '?')} "
                f"({entry.get('confidence', '?')})"
            )
        return "\n".join(lines)

    if cmd == "/questions":
        questions = _read_json(PENDING_QUESTIONS_FILE, [])
        if not questions:
            return "No pending questions."
        lines = ["*Pending Questions:*"]
        for q in questions:
            age_h = (time.time() - q.get("created", 0)) / 3600
            lines.append(
                f"  Q{q['id']} ({q.get('project', '?')}): "
                f"{q.get('question', '')[:60]} [{age_h:.1f}h ago]"
            )
        return "\n".join(lines)

    return f"Unknown command: {cmd}"


# ---------------------------------------------------------------------------
# Interactive questions (inline buttons)
# ---------------------------------------------------------------------------

def ask_question(project: str, question: str, choices: list[str],
                 context: str = "") -> dict:
    """Send an interactive question with inline buttons or force_reply.

    Args:
        project: Project name.
        question: The question text.
        choices: List of valid answers (e.g. ["yes", "no"]). Empty = free text.
        context: Optional context tag for response handling (e.g. "drift_detected").

    Returns:
        Dict with question ID and status.
    """
    if not is_configured():
        return {"sent": False, "detail": "Bot not configured"}

    qid = int(time.time())

    text = f"Question #{qid} for *{project}*:\n{question}"

    message_id = None

    if choices:
        # Inline buttons for multiple choice
        buttons = [{"text": c, "data": f"q:{qid}:{c}"} for c in choices]
        sent = send_reply(str(TELEGRAM_CHAT_ID), text, buttons=buttons)
        # Fetch the message_id by sending via _api_call directly to capture it
        payload = {
            "chat_id": str(TELEGRAM_CHAT_ID),
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": [[{"text": b["text"], "callback_data": b["data"]} for b in buttons]],
            },
        }
        result = _api_call("sendMessage", payload)
        if result and "result" in result:
            message_id = result["result"].get("message_id")
        sent = result is not None
    else:
        # Free-text: send with force_reply
        payload = {
            "chat_id": str(TELEGRAM_CHAT_ID),
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {"force_reply": True},
        }
        result = _api_call("sendMessage", payload)
        if result and "result" in result:
            message_id = result["result"].get("message_id")
        sent = result is not None

    # Store the question
    questions = _read_json(PENDING_QUESTIONS_FILE, [])
    questions.append({
        "id": qid,
        "project": project,
        "question": question,
        "choices": choices,
        "context": context,
        "created": qid,
        "message_id": message_id,
        "open_ended": len(choices) == 0,
    })
    _write_json(PENDING_QUESTIONS_FILE, questions)

    return {"sent": sent, "id": qid, "choices": choices}


def check_responses(callbacks: list[dict]) -> list[dict]:
    """Match callback button presses to pending questions.

    Args:
        callbacks: List of callback dicts from poll().

    Returns list of answered questions. Auto-expires questions older than 24h.
    """
    questions = _read_json(PENDING_QUESTIONS_FILE, [])
    if not questions:
        return []

    now = time.time()
    expired = []
    answered = []

    # Parse callback data: "q:<id>:<choice>"
    cb_map = {}
    for cb in callbacks:
        data = cb.get("data", "")
        if data.startswith("q:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                try:
                    cb_map[int(parts[1])] = parts[2]
                except ValueError:
                    pass

    remaining = []
    for q in questions:
        age = now - q.get("created", 0)

        # Auto-expire after 24 hours
        if age > 86400:
            expired.append(q)
            continue

        # Check for a button press matching this question
        qid = q["id"]
        if qid in cb_map:
            answer = cb_map[qid].lower()
            if answer in [c.lower() for c in q["choices"]]:
                answered.append({
                    "id": qid,
                    "project": q["project"],
                    "question": q["question"],
                    "answer": answer,
                    "context": q.get("context", ""),
                    "chat_id": cb["chat_id"],
                    "message_id": cb.get("message_id"),
                })
                continue

        remaining.append(q)

    # Notify about expired questions
    for q in expired:
        send_reply(
            str(TELEGRAM_CHAT_ID),
            f"Question #{q['id']} for *{q['project']}* expired (24h).",
        )

    # Persist remaining questions
    _write_json(PENDING_QUESTIONS_FILE, remaining)

    return answered


def check_text_replies(messages: list[dict]) -> list[dict]:
    """Match text replies to pending open-ended questions.

    Uses reply_to_message_id matching, or falls back to the oldest
    pending open question.

    Returns answered questions in the same format as check_responses().
    """
    questions = _read_json(PENDING_QUESTIONS_FILE, [])
    if not questions:
        return []

    now = time.time()
    answered = []

    # Only consider open-ended questions (no choices)
    open_questions = [q for q in questions if q.get("open_ended") and now - q.get("created", 0) < 86400]

    if not open_questions:
        return []

    # Build a map of reply_to_message_id -> message for quick lookup
    reply_map = {}
    for msg in messages:
        rtid = msg.get("reply_to_message_id")
        if rtid and msg.get("text") and not msg["text"].startswith("/"):
            reply_map[rtid] = msg

    remaining = list(questions)

    # First pass: match by reply_to_message_id
    for q in open_questions:
        q_msg_id = q.get("message_id")
        if q_msg_id and q_msg_id in reply_map:
            msg = reply_map[q_msg_id]
            answered.append({
                "id": q["id"],
                "project": q["project"],
                "question": q["question"],
                "answer": msg["text"],
                "context": q.get("context", ""),
                "chat_id": msg["chat_id"],
                "message_id": q_msg_id,
            })
            remaining.remove(q)

    # Second pass: if no reply_to match but there are open questions and
    # unmatched non-command messages, assign to oldest open question
    unmatched_msgs = [
        m for m in messages
        if m.get("text") and not m["text"].startswith("/")
        and m.get("reply_to_message_id") not in reply_map
    ]
    still_open = [q for q in remaining if q.get("open_ended") and now - q.get("created", 0) < 86400]
    for msg in unmatched_msgs:
        if not still_open:
            break
        # Assign to oldest open question
        q = still_open.pop(0)
        answered.append({
            "id": q["id"],
            "project": q["project"],
            "question": q["question"],
            "answer": msg["text"],
            "context": q.get("context", ""),
            "chat_id": msg["chat_id"],
            "message_id": q.get("message_id"),
        })
        remaining.remove(q)

    # Expire old questions
    still_remaining = []
    for q in remaining:
        age = now - q.get("created", 0)
        if age > 86400:
            send_reply(
                str(TELEGRAM_CHAT_ID),
                f"Question #{q['id']} for *{q['project']}* expired (24h).",
            )
        else:
            still_remaining.append(q)

    _write_json(PENDING_QUESTIONS_FILE, still_remaining)

    return answered
