from datetime import date, datetime, timedelta


def schedule(previous: dict | None, recall: str, mastery: float | None) -> tuple[int, int, str]:
    """Self-reported recall, capped by observed coverage. No inference when assessment is absent."""
    interval = previous["interval_days"] if previous else 0
    repetitions = previous["repetitions"] if previous else 0
    if mastery is not None and mastery < 0.5:
        recall = "again"
    elif mastery is not None and mastery < 0.8 and recall == "easy":
        recall = "hard"
    if recall == "again":
        days, repetitions = 1, 0
    elif recall == "hard":
        days, repetitions = max(2, round(interval * 1.2)), repetitions + 1
    elif recall == "good":
        days, repetitions = (3 if interval == 0 else max(3, round(interval * 2))), repetitions + 1
    else:
        days, repetitions = (7 if interval == 0 else max(7, round(interval * 2.5))), repetitions + 1
    days = min(days, 90)
    last_completed = previous.get("last_completed_at") if previous else None
    if last_completed and datetime.fromisoformat(last_completed).astimezone().date() == date.today():
        # Repeating immediately can shorten a review, but cannot establish durable recall.
        days = min(days, previous["interval_days"])
        repetitions = min(repetitions, previous["repetitions"])
    return days, repetitions, (date.today() + timedelta(days=days)).isoformat()


def mastery(assessment: dict | None) -> float | None:
    if not assessment:
        return None
    return sum(c["status"] == "correct" for c in assessment["concepts"]) / len(assessment["concepts"])


def compare(first: dict, second: dict, prior: dict | None) -> dict:
    a = {c["concept_id"]: c for c in (first.get("assessment") or {}).get("concepts", [])}
    b = {c["concept_id"]: c for c in (second.get("assessment") or {}).get("concepts", [])}
    return {
        "available": bool(a and b),
        "newly_demonstrated": [
            k for k, c in b.items() if c["status"] == "correct" and a.get(k, {}).get("status") != "correct"
        ]
        if a
        else [],
        "corrected": [
            k for k, c in b.items() if c["status"] == "correct" and a.get(k, {}).get("status") == "incorrect"
        ],
        "remaining": [k for k, c in b.items() if c["status"] != "correct"],
        "prior_session": prior,
        "note": "This comparison shows immediate learning. A future cold attempt provides evidence of retention.",
    }
