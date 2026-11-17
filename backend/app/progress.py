import json
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
    """Share of concepts shown correct. Works on the legacy assessment and on analysis.technical."""
    if not assessment or not assessment.get("concepts"):
        return None
    return sum(c["status"] == "correct" for c in assessment["concepts"]) / len(assessment["concepts"])


def derived_recall(mastery: float | None) -> str:
    """Recall inferred from attempt 2: the learner no longer rates themselves."""
    if mastery is not None and mastery >= 0.8:
        return "good"
    if mastery is not None and mastery >= 0.5:
        return "hard"
    return "again"


def concept_results(attempt: dict) -> dict | None:
    """Per-concept results of a raw attempt row: the new technical pass, else the legacy assessment."""
    analysis = json.loads(attempt["analysis"]) if attempt.get("analysis") else None
    technical = (analysis or {}).get("technical")
    if technical and technical.get("concepts"):
        return technical
    return json.loads(attempt["assessment"]) if attempt.get("assessment") else None
