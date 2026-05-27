"""Smart Loops — Telegram notifications."""

import json
import urllib.request
import urllib.error

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(project_name: str, message: str) -> dict:
    """Send a Telegram notification.

    Returns dict with success (bool) and detail (str).
    """
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token:
        return {"success": False, "detail": "SMARTLOOPS_TELEGRAM_TOKEN not set"}
    if not chat_id:
        return {"success": False, "detail": "SMARTLOOPS_TELEGRAM_CHAT_ID not set"}

    text = f"*Smart Loops | {project_name}*\n{message}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return {"success": True, "detail": "Message sent"}
            return {"success": False, "detail": f"Telegram error: {body.get('description', 'unknown')}"}
    except urllib.error.URLError as e:
        return {"success": False, "detail": f"Network error: {e.reason}"}
    except Exception as e:
        return {"success": False, "detail": f"Error: {e}"}


def send_rich_alert(project_name: str, title: str, body: str,
                    severity: str = "info") -> dict:
    """Send a structured alert with severity prefix and formatted body.

    Backward compatible — existing send_message() is unchanged.
    """
    severity_icons = {
        "info": "INFO",
        "warning": "WARN",
        "error": "ERROR",
        "critical": "CRITICAL",
    }
    label = severity_icons.get(severity, severity.upper())

    text = (
        f"*Smart Loops | {project_name}*\n"
        f"[{label}] {title}\n\n"
        f"```\n{body[:3500]}\n```"
    )

    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID

    if not token or not chat_id:
        return {"success": False, "detail": "Telegram not configured"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                return {"success": True, "detail": "Rich alert sent"}
            return {"success": False, "detail": f"Telegram error: {result.get('description', 'unknown')}"}
    except urllib.error.URLError as e:
        return {"success": False, "detail": f"Network error: {e.reason}"}
    except Exception as e:
        return {"success": False, "detail": f"Error: {e}"}
