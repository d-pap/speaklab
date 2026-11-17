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
