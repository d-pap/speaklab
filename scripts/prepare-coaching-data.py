#!/usr/bin/env python3
"""Inventory private reference conversations and export explicitly reviewed examples. No model calls."""

import argparse
import hashlib
import json
from pathlib import Path

QUALITY_TARGETS = [
    "Notice specific communication patterns and knowledge gaps without being told what to notice.",
    "Support observations with the transcript; separate evidence from tentative interpretation.",
    "Distinguish missing understanding from difficulty expressing an understood idea.",
    "Correct technical mistakes accurately without treating omissions as errors.",
    "Teach from prerequisites using examples, tradeoffs and checks of understanding.",
    "Prioritize actionable practice while preserving personality and a conversational style.",
]


def inventory(directory: Path) -> list[dict]:
    return [
        {
            "source": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "status": "reference_only_context_and_completeness_unverified",
            "split": "unassigned",
        }
        for path in sorted(directory.glob("*.md"))
    ]


def prepare(directory: Path, examples: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    sources = inventory(directory)
    by_name = {s["source"]: s for s in sources}
    splits, seen, content_splits = {}, set(), {}
    train, evaluation = [], []
    for item in examples:
        key = item["id"]
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError("Every example needs a unique, nonempty ID.")
        seen.add(key)
        source = by_name[item["source"]]
        if item["source_sha256"] != source["sha256"]:
            raise ValueError(f"{key}: reference changed; verify the source again.")
        split = item["split"]
        if split not in {"train", "eval"} or item["task"] not in {"review", "learn"}:
            raise ValueError(f"{key}: choose train/eval and review/learn explicitly.")
        if item.get("context_verified") is not True or item.get("quality_reviewed") is not True:
            raise ValueError(f"{key}: verify context, completeness and target quality before export.")
        group = source["sha256"]  # all turns from a conversation stay in one split
        if group in splits and splits[group] != split:
            raise ValueError("A reference conversation cannot appear in both training and evaluation.")
        splits[group] = split
        messages = item["messages"]
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError(f"{key}: include the input and the assistant response.")
        if messages[-1].get("role") != "assistant" or messages[-2].get("role") != "user":
            raise ValueError(f"{key}: finish with a user input and its assistant target.")
        original = (directory / source["source"]).read_text()
        for message in messages:
            if set(message) != {"role", "content"} or message["role"] not in {"system", "user", "assistant"}:
                raise ValueError(f"{key}: messages require role and content only.")
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"{key}: empty message.")
            if message["role"] != "system" and content not in original:
                raise ValueError(f"{key}: preserve source text verbatim, including the target.")
            normalized = " ".join(content.split())
            if message["role"] != "system" and len(normalized) >= 100:
                fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
                if fingerprint in content_splits and content_splits[fingerprint] != split:
                    raise ValueError("Duplicate conversation content crosses the train/eval split.")
                content_splits[fingerprint] = split
        record = {
            "id": key, "source": item["source"], "source_sha256": group,
            "task": item["task"], "messages": messages,
        }
        (train if split == "train" else evaluation).append(record)
    for source in sources:
        if source["sha256"] in splits:
            source["split"] = splits[source["sha256"]]
            source["status"] = "contains_explicitly_reviewed_examples"
    manifest = {
        "format": "speaklab-reference-corpus-v1", "quality_targets": QUALITY_TARGETS,
        "sources": sources, "train_examples": len(train), "eval_examples": len(evaluation),
        "limitations": "Shared-page captures may omit replies. Reference approval is not verification of every claim. "
                        "No model quality improvement has been measured. No training is performed.",
    }
    return manifest, train, evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--examples", type=Path, help="JSON array of explicitly reviewed examples")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.references.is_dir():
        parser.error("The reference directory does not exist.")
    try:
        examples = json.loads(args.examples.read_text()) if args.examples else []
        manifest, train, evaluation = prepare(args.references, examples)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name, rows in (("train.sft", [{"messages": r["messages"]} for r in train]), ("eval", evaluation)):
        (args.output / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    # Keep training provenance out of the model's input, beside the messages-only SFT data.
    (args.output / "train.provenance.json").write_text(json.dumps(train, indent=2) + "\n")
    print(f"Inventoried {len(manifest['sources'])} references; exported {len(train)} training and {len(evaluation)} evaluation examples.")


if __name__ == "__main__":
    main()
