import json
import random
from datetime import date
from pathlib import Path

TOPICS = json.loads(Path(__file__).with_name("topics.json").read_text())
CATALOG = {t["id"]: t for t in TOPICS}


def prompt(topic: dict, kind: str) -> str:
    return {
        "Concept explanation": topic["prompt"],
        "How it works": f"Walk another engineer through how {topic['title'].lower()} works, step by step.",
        "Compare": topic["compare"],
        "Trade-off": f"Explain a benefit, a cost, and a case where {topic['title'].lower()} may be the wrong choice.",
        "Defend a decision": f"Choose a practical use of {topic['title'].lower()}. Defend your choice and discuss an alternative.",
        "Nontechnical audience": f"Explain {topic['title'].lower()} to a curious nontechnical colleague using an everyday example.",
    }[kind]


def public_topic(topic: dict) -> dict:
    return {k: topic[k] for k in ("id", "title", "category", "difficulty", "prompt")}


def recommend(candidates: list[dict], reviews: dict, weak: dict) -> dict:
    today = date.today().isoformat()
    weights = []
    for topic in candidates:
        review = reviews.get(topic["id"])
        weight = 3 if not review else (8 if review["due"] <= today else 0.5)
        weight += 4 * weak.get(topic["id"], 0)
        weights.append(weight)
    return random.choices(candidates, weights=weights, k=1)[0]


def lesson(topic: dict, assessment: dict | None) -> dict:
    results = {c["concept_id"]: c["status"] for c in assessment["concepts"]} if assessment else {}
    gaps = [c for c in topic["concepts"] if results.get(c["id"]) != "correct"]
    if not gaps:
        gaps = topic["concepts"][-2:]
    return {
        "estimated_minutes": 18,
        "personalized": bool(assessment),
        "objectives": [f"Explain {c['name'].lower()} in your own words." for c in gaps],
        "sections": [
            {
                "title": "Core idea",
                "minutes": 2,
                "body": topic["core"],
                "context": topic.get("background", ""),
                "question": "How would you explain the central idea in one sentence?",
            },
            *[
                {
                    "title": c["name"],
                    "minutes": max(1, 10 // len(gaps)),
                    "body": c["reference"],
                    "context": c.get("bridge", ""),
                    "question": c["check"],
                }
                for c in gaps
            ],
            {
                "title": "Put it into practice",
                "minutes": 3,
                "body": topic["example"],
                "practice": topic.get("practice", ""),
                "question": "Can you invent a different example and explain why it works?",
            },
            {
                "title": "Important nuances",
                "minutes": 3,
                "body": topic["nuance"],
                "question": "What trade-off or limitation would you mention to another engineer?",
            },
        ],
        "sources": topic["sources"],
        "reviewed_at": topic.get("reviewed_at"),
    }
