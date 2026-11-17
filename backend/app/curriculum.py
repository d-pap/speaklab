import json
import random
from datetime import date
from pathlib import Path

TOPICS = json.loads(Path(__file__).with_name("topics.json").read_text())
CATALOG = {t["id"]: t for t in TOPICS}


def topic_for(topic_id: str) -> dict:
    """The catalog topic, or a minimal stand-in for a topic no longer in the catalog.

    Saved sessions outlive catalog edits; a missing topic must not break history or review pages.
    """
    if topic_id in CATALOG:
        return CATALOG[topic_id]
    return {
        "id": topic_id,
        "title": topic_id.replace("-", " ").capitalize(),
        "category": "Retired topic",
        "difficulty": "intermediate",
        "prompt": "",
        "compare": "",
        "concepts": [],
        "sources": [],
        "background": "",
        "practice": "",
    }


def prompt(topic: dict, kind: str) -> str:
    # Sessions saved with a prompt kind this version no longer offers fall back to the topic prompt.
    return {
        "Concept explanation": topic["prompt"],
        "How it works": f"Walk another engineer through how {topic['title'].lower()} works, step by step.",
        "Compare": topic["compare"],
        "Trade-off": f"Explain a benefit, a cost, and a case where {topic['title'].lower()} may be the wrong choice.",
        "Defend a decision": f"Choose a practical use of {topic['title'].lower()}. Defend your choice and discuss an alternative.",
        "Nontechnical audience": f"Explain {topic['title'].lower()} to a curious nontechnical colleague using an everyday example.",
    }.get(kind, topic["prompt"])


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
