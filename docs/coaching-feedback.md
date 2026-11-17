# Improving local coaching from feedback

SpeakLab collects feedback on the opening review and each learning-chat response. A vote can include a reason, a comment and a preferred response. Clicking the selected thumb removes the vote. Settings → Coaching feedback downloads the local records as JSON. No model calls, coach-note edits or training happen when feedback is saved.

Each new response keeps its actual model request, options and raw completion, plus transcript lines and analysis at generation time. Review marker-repair requests are retained too. The feedback snapshot preserves the displayed response and this context when first rated; changing a vote never replaces the snapshot. Re-reviews, transcript edits and replacement recordings cannot erase rated evidence. Older responses without generation records are explicitly marked as lacking original context. Current prompts are never substituted for missing historical prompts.

The export is uncurated evidence, not a training dataset. A vote rates the visible response as a whole: it does not identify which technical, communication or writer pass caused a problem. A preferred answer is a proposed correction, not automatically verified truth. Truncated responses and marker repairs need review before becoming training examples. Source context and raw model text can differ from what was displayed after marker cleanup.

The conversation's model picker changes the common model for subsequent reviews and replies across SpeakLab. Regenerate review reruns all review passes under the current settings, preserving earlier feedback in the archive and rated evidence in the export. Each response labels its producing model. Per-step choices made in Settings remain active until an explicit common-model selection. Comparisons for model-quality claims must also hold prompts, notes and other context constant; a normal regeneration uses current context and is not a controlled evaluation by itself.

## Quality target

Evaluate both the quality of the answer and the judgment behind it:

- Does the coach notice specific patterns without the learner pointing them out?
- Does it support those observations with the transcript and qualify uncertain diagnoses?
- Does it distinguish a knowledge gap from trouble expressing an understood idea?
- Are technical corrections accurate, with omissions distinguished from errors?
- Does teaching build the missing understanding with examples and useful follow-ups?
- Are the response style and next practice steps clear, specific and usable?

Visible explanations and evidence can be assessed. A conversation export does not expose a teacher model's hidden reasoning. Matching writing style alone does not establish equivalent reasoning or coaching quality.

## Reference conversations

Keep private conversations and derived datasets under `.local/`, outside Git and source deployment archives. Preserve each complete user input and the context available before its assistant response, including earlier teaching turns when necessary. Never give an initial-review evaluation the learner's later agreement, diagnosis or preferred answer: that would reveal what the coach was meant to discover unaided.

Inventory a directory of saved Markdown conversations without enrolling any in training:

```sh
.venv/bin/python scripts/prepare-coaching-data.py \
  --references .local/reference-reviews \
  --output .local/coaching-corpus
```

The manifest records source hashes, quality targets and unverified completeness. Shared-page captures may be incomplete. Keep them as qualitative references until individual examples have been checked. Broader conversation approval does not certify every factual claim.

To export reviewed examples, supply `--examples .local/reviewed-examples.json`, a JSON array with this shape:

```json
[
  {
    "id": "example-1",
    "source": "conversation.md",
    "source_sha256": "hash from manifest.json",
    "task": "review",
    "split": "eval",
    "context_verified": true,
    "quality_reviewed": true,
    "messages": [
      {"role": "user", "content": "Verbatim complete input from the source"},
      {"role": "assistant", "content": "Verbatim complete target response from the source"}
    ]
  }
]
```

Use `task: "learn"` for teaching exchanges and include preceding conversation turns as needed. The tool checks source hashes, verbatim spans, explicit review flags and conversation-level train/evaluation separation. It also rejects long duplicate spans across splits. Human verification must still establish that context is complete, ordered and free of future-answer leakage. `train.sft.jsonl` contains messages only; provenance and evaluation metadata are exported separately. Running without examples writes empty training/evaluation files and an inventory only.

Before training, pin whole conversations to either training or evaluation and collect additional independent attempts. Examples already used to design prompts are development references, not an unbiased final test. Do not claim a held-out result from a conversation used to tune prompts or weights. Group local feedback examples by topic thread to avoid related attempts leaking across the split. A handful of admired conversations establishes the target, not a demonstrated training benefit.

The next experiment compares the current local model with a candidate on identical unseen inputs, judging unprompted observations, factual accuracy, diagnosis, teaching and style separately. Train a separate version or adapter and switch only after evaluation. Hardware feasibility, data sufficiency and coaching improvements remain unmeasured.
