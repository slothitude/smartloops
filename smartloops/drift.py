"""Smart Loops — Drift detection.

Compares current work against registered project goal to detect misalignment.
"""


def detect_drift(name: str) -> dict:
    """Check if a project has drifted from its goal.

    Returns dict with: drifted (bool), current_focus, expected_focus, suggestion
    """
    from smartloops import db, claude_log

    project = db.get_project(name)
    if not project:
        return {"error": f"Project '{name}' not found"}

    goal = project.get("goal", "").lower()
    path = project["path"]

    if not goal:
        return {"drifted": False, "reason": "No goal defined, cannot detect drift"}

    # Get Claude's recent tasks
    try:
        log_entries = claude_log.parse_entries(path)
    except Exception:
        return {"drifted": False, "reason": "Could not parse Claude log"}
    if not log_entries:
        return {"drifted": False, "reason": "No Claude activity to analyze"}

    # Extract keywords from goal
    goal_keywords = _extract_keywords(goal)

    # Extract keywords from recent tasks
    recent_tasks = log_entries[-5:] if len(log_entries) >= 5 else log_entries
    task_texts = []
    for entry in recent_tasks:
        task = entry.get("task", "")
        if task:
            task_texts.append(task)

    if not task_texts:
        return {"drifted": False, "reason": "No task descriptions found"}

    # Check overlap between task keywords and goal keywords
    all_task_keywords = set()
    for task in task_texts:
        all_task_keywords.update(_extract_keywords(task))

    overlap = goal_keywords & all_task_keywords
    overlap_ratio = len(overlap) / len(goal_keywords) if goal_keywords else 0

    current_focus = ", ".join(task_texts[-2:]) if len(task_texts) >= 2 else task_texts[0] if task_texts else "unknown"

    # Determine drift
    drifted = False
    suggestion = ""

    if overlap_ratio == 0 and len(recent_tasks) >= 3:
        drifted = True
        suggestion = (f"Recent work has no overlap with project goal. "
                      f"Goal keywords: {', '.join(sorted(goal_keywords))}. "
                      f"Consider refocusing on the original objective.")
    elif overlap_ratio < 0.2 and len(recent_tasks) >= 3:
        drifted = True
        suggestion = (f"Minimal overlap with project goal ({overlap_ratio:.0%}). "
                      f"Current work may be tangential. Review if this is needed.")
    elif overlap_ratio < 0.4:
        suggestion = "Slight drift possible — work is loosely related to the goal."

    return {
        "drifted": drifted,
        "goal": project["goal"],
        "current_focus": current_focus,
        "goal_keywords": sorted(goal_keywords),
        "task_keywords": sorted(all_task_keywords),
        "overlap": sorted(overlap),
        "overlap_ratio": round(overlap_ratio, 2),
        "suggestion": suggestion,
    }


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text (remove stop words)."""
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but", "and",
        "or", "if", "while", "about", "up", "it", "its", "this", "that",
        "these", "those", "i", "me", "my", "we", "our", "you", "your", "he",
        "him", "his", "she", "her", "they", "them", "their", "what", "which",
        "who", "whom", "build", "create", "make", "add", "new",
    }

    words = text.lower().replace("-", " ").replace("_", " ").split()
    keywords = set()
    for w in words:
        w = w.strip(".,;:!?")
        if len(w) >= 3 and w not in stop_words:
            keywords.add(w)
    return keywords
