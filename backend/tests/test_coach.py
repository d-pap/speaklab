import json

import httpx
import pytest
from conftest import Reply

from app import coach, llm, models
from app.config import settings
from app.curriculum import CATALOG

TOPIC = CATALOG["hash-maps"]
CORE = [
    "Overall",
    "Clarity",
    "Structure",
    "Conciseness",
    "Technical accuracy",
    "Technical coverage",
    "Handling uncertainty",
]
LINES = [
    {"id": "L1", "start": 0.0, "end": 4.0, "text": "A hash map stores keys and values so you find a value by key."},
    {"id": "L2", "start": 4.0, "end": 9.0, "text": "It hashes the key to pick a bucket, so lookup is constant time."},
    {
        "id": "L3",
        "start": 9.5,
        "end": 15.0,
        "text": "Um, a collision is when two keys share a bucket and the second overwrites the first.",
    },
    {"id": "L4", "start": 15.0, "end": 20.0, "text": "Counting words in a document is a good example of using one."},
]


def untimed(lines):
    return [{**line, "start": None, "end": None} for line in lines]


def technical_reply(**overrides):
    data = {
        "concepts": [
            {"concept_id": "hashing", "status": "correct", "line_ids": ["L2"], "note": "Hash picks a bucket."},
            {"concept_id": "collisions", "status": "incorrect", "line_ids": ["L3"], "note": "Says entries overwrite."},
            {"concept_id": "complexity", "status": "partial", "line_ids": ["L2"], "note": "Constant time, no caveat."},
            {"concept_id": "resizing", "status": "missing", "line_ids": [], "note": "Not reached."},
        ],
        "corrections": [
            {
                "line_id": "L3",
                "claim": "Colliding keys overwrite each other.",
                "correction": "Both entries are kept; the map compares the actual keys.",
                "basis": "reference",
                "reference_ids": ["collisions"],
            }
        ],
        "senior_points": [
            {"point": "Equal keys must hash equally.", "basis": "reference"},
            {"point": "Collisions are resolved by chaining or probing.", "basis": "reference"},
            {"point": "Resizing keeps the load factor bounded.", "basis": "reference"},
        ],
    }
    data.update(overrides)
    return data


def confirm(*ids, verdict="incorrect", reference_ids=("collisions",)):
    return {
        "reviews": [
            {
                "id": i,
                "verdict": verdict,
                "explanation": "The words conflict with the reference.",
                "correction": "",
                "reference_ids": list(reference_ids),
            }
            for i in ids
        ]
    }


def last_user_message(request):
    return [m for m in request["messages"] if m["role"] == "user"][-1]["content"]


# Technical pass


def test_technical_pass_rejects_unknown_line_ids_then_repairs(fake_llm):
    bad = technical_reply()
    bad["concepts"][0]["line_ids"] = ["L99"]
    bad["corrections"][0]["line_id"] = "L42"
    fake_llm.queue("technical", bad, technical_reply(), confirm("C1"))

    result, model_used = coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    assert model_used == settings.ollama_model
    first, repair, check = fake_llm.requests_for("technical")
    # Both bad IDs are reported in the single repair request.
    assert "L99" in last_user_message(repair) and "L42" in last_user_message(repair)
    # The schema sent to the model constrains line IDs to the transcript.
    schema = first["payload"]["output_schema"]
    assert schema["$defs"]["ConceptFinding"]["properties"]["line_ids"]["items"]["enum"] == ["L1", "L2", "L3", "L4"]
    assert first["body"]["format"] == schema
    assert first["payload"]["transcript_lines"] == {line["id"]: line["text"] for line in LINES}
    assert result["concepts"][0]["line_ids"] == ["L2"]
    assert result["corrections"][0]["line_id"] == "L3"
    assert result["corrections"][0]["verified"] is True
    assert "proposed_corrections" in check["payload"]


def test_technical_pass_has_one_result_per_concept(fake_llm):
    bad = technical_reply()
    bad["concepts"] = bad["concepts"][:3] + [dict(bad["concepts"][0])]  # resizing missing, hashing twice
    fake_llm.queue("technical", bad, technical_reply(corrections=[]))

    result, _ = coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    first, repair = fake_llm.requests_for("technical")  # no corrections, so no second check
    assert "resizing" in last_user_message(repair)
    concept_schema = first["payload"]["output_schema"]["properties"]["concepts"]
    assert concept_schema["minItems"] == concept_schema["maxItems"] == 4
    enum = first["payload"]["output_schema"]["$defs"]["ConceptFinding"]["properties"]["concept_id"]["enum"]
    assert enum == [c["id"] for c in TOPIC["concepts"]]
    assert [c["concept_id"] for c in result["concepts"]] == [c["id"] for c in TOPIC["concepts"]]


def test_technical_pass_missing_concept_cites_no_lines(fake_llm):
    bad = technical_reply(corrections=[])
    bad["concepts"][3]["line_ids"] = ["L4"]  # missing, yet cited
    bad["concepts"][0]["line_ids"] = []  # correct, yet uncited
    fake_llm.queue("technical", bad, technical_reply(corrections=[]))

    coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    message = last_user_message(fake_llm.requests_for("technical")[1])
    assert "resizing" in message and "hashing" in message


def test_reference_basis_requires_reference_id(fake_llm):
    no_ref = technical_reply()
    no_ref["corrections"][0]["reference_ids"] = []
    unknown_ref = technical_reply()
    unknown_ref["corrections"][0]["reference_ids"] = ["wikipedia"]
    fake_llm.queue("technical", no_ref, unknown_ref)

    with pytest.raises(models.ServiceUnavailable):
        coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    message = last_user_message(fake_llm.requests_for("technical")[1])
    assert "reference_ids" in message
    allowed = fake_llm.requests_for("technical")[0]["payload"]["output_schema"]["$defs"]["Correction"]
    assert set(allowed["properties"]["reference_ids"]["items"]["enum"]) == (
        {c["id"] for c in TOPIC["concepts"]} | {c["id"] + "_context" for c in TOPIC["concepts"]} | {"practice"}
    )


def test_reference_basis_accepts_context_and_practice_ids(fake_llm):
    reply = technical_reply()
    reply["corrections"][0]["reference_ids"] = ["collisions_context", "practice"]
    fake_llm.queue("technical", reply, confirm("C1", reference_ids=()))

    result, _ = coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    assert result["corrections"][0]["reference_ids"] == ["collisions_context", "practice"]


# Correction second check


def corrections(*line_ids):
    return [
        {
            "line_id": line_id,
            "claim": f"Claim on {line_id}.",
            "correction": f"Correction for {line_id}.",
            "basis": "reference",
            "reference_ids": ["collisions"],
        }
        for line_id in line_ids
    ]


def test_verify_corrections_marks_unverified_when_second_call_fails(fake_llm):
    fake_llm.queue("technical", httpx.ConnectError("model down"))

    result = coach.verify_corrections(TOPIC, LINES, corrections("L2", "L3"))

    assert [c["line_id"] for c in result] == ["L2", "L3"]
    assert all(c["verified"] is False for c in result)


def test_verify_corrections_removes_withdrawn(fake_llm):
    reply = {
        "reviews": [
            {"id": "C1", "verdict": "supported", "explanation": "Consistent.", "correction": "", "reference_ids": []},
            {
                "id": "C2",
                "verdict": "incorrect",
                "explanation": "Conflicts.",
                "correction": "The map keeps both colliding entries.",
                "reference_ids": ["collisions"],
            },
            {"id": "C3", "verdict": "unverified", "explanation": "Can't settle.", "correction": "", "reference_ids": []},
        ]
    }
    fake_llm.queue("technical", reply)

    result = coach.verify_corrections(TOPIC, LINES, corrections("L1", "L3", "L4"))

    assert [(c["line_id"], c["verified"]) for c in result] == [("L3", True), ("L4", False)]
    assert result[0]["correction"] == "The map keeps both colliding entries."
    request = fake_llm.requests_for("technical")[0]
    assert [p["id"] for p in request["payload"]["proposed_corrections"]] == ["C1", "C2", "C3"]
    schema = request["payload"]["output_schema"]
    assert schema["properties"]["reviews"]["minItems"] == schema["properties"]["reviews"]["maxItems"] == 3
    # The legacy second-check instructions moved over with line IDs instead of excerpt IDs.
    assert "Withdraw a correction unless the ACTUAL words conflict with the reference." in coach.VERIFY_SYSTEM
    assert "excerpt" not in coach.VERIFY_SYSTEM


def test_verify_corrections_without_corrections_makes_no_call(fake_llm):
    assert coach.verify_corrections(TOPIC, LINES, []) == []
    assert fake_llm.requests == []


# Communication pass


def communication_reply(**overrides):
    data = {
        "sections": [
            {"label": "Definition", "first_line": "L1", "last_line": "L2"},
            {"label": "Collisions", "first_line": "L3", "last_line": "L3"},
            {"label": "Example", "first_line": "L4", "last_line": "L4"},
        ],
        "points": [
            {"kind": "strength", "line_id": "L1", "observation": "Opens with a plain definition.", "rewrite": ""},
            {
                "kind": "problem",
                "line_id": "L4",
                "observation": "The example arrives last without the lookup step.",
                "rewrite": "Say you count words: each word is a key, and its count is the value.",
            },
        ],
        "gaps": [{"section_label": "Collisions", "kind": "knowledge", "reason": "The mechanism is misstated."}],
        "focus": [{"area": "Lead with an example", "observation": "The example came at the end."}],
    }
    data.update(overrides)
    return data


NOTES = "## Focus areas\n- Lead with an example (since 2026-11-10)\n\n## Goals\n- Senior interviews"
VOICE = ["Longest pause 1.6s before line L3.", "Pace slowed in the collisions part.", "Two fillers."]


def test_communication_prompt_contains_coach_notes_and_voice_summary(fake_llm):
    fake_llm.queue("communication", communication_reply())

    result, _ = coach.communication_pass(LINES, VOICE, NOTES, {"prompt": TOPIC["prompt"], "duration": 21.0})

    payload = fake_llm.requests_for("communication")[0]["payload"]
    assert payload["coach_notes"] == NOTES
    assert payload["voice_summary"] == VOICE
    assert payload["prompt"] == TOPIC["prompt"]
    assert payload["transcript_lines"]["L3"] == LINES[2]["text"]
    assert [s["label"] for s in result["sections"]] == ["Definition", "Collisions", "Example"]


def test_communication_sections_must_be_ordered_and_not_overlap(fake_llm):
    bad = communication_reply(
        sections=[
            {"label": "Definition", "first_line": "L2", "last_line": "L1"},
            {"label": "Collisions", "first_line": "L1", "last_line": "L3"},
            {"label": "Example", "first_line": "L4", "last_line": "L9"},
        ]
    )
    fake_llm.queue("communication", bad, communication_reply())

    coach.communication_pass(LINES, VOICE, NOTES, {"prompt": TOPIC["prompt"], "duration": 21.0})

    message = last_user_message(fake_llm.requests_for("communication")[1])
    assert "Definition" in message and "Collisions" in message and "L9" in message


# Section timing


SECTIONS = communication_reply()["sections"]


def test_section_timing_percentages_sum_to_100_when_timed():
    timing = coach.section_timing(SECTIONS, LINES, 21.0)

    assert [t["label"] for t in timing] == ["Definition", "Collisions", "Example"]
    assert timing[0]["start"] == 0.0 and timing[1]["start"] == 9.5
    assert timing[0]["seconds"] == pytest.approx(9.5)
    assert timing[2]["end"] == 20.0
    assert sum(t["percent"] for t in timing) == pytest.approx(100, abs=0.01)


def test_section_timing_empty_when_untimed():
    assert coach.section_timing(SECTIONS, untimed(LINES), 21.0) == []


# Review structure


def scores(values=None, names=CORE):
    values = values or {}
    return [{"name": n, "score": values.get(n, 6.5), "reason": f"{n} reason."} for n in names]


TECHNICAL = {**technical_reply(), "corrections": [{**technical_reply()["corrections"][0], "verified": True}]}
COMMUNICATION = communication_reply()
TIMING = coach.section_timing(SECTIONS, LINES, 21.0)


def structure_reply(**overrides):
    data = {
        "scores": scores(),
        "key_points": [
            {"text": "Collisions are misstated.", "line_ids": ["L3"]},
            {"text": "The example comes too late.", "line_ids": ["L4"]},
            {"text": "Constant time needs its caveat.", "line_ids": ["L2"]},
        ],
        "checklist": ["Open with the word-count example.", "Say what happens on a collision."],
        "comparison": None,
    }
    data.update(overrides)
    return data


def test_review_structure_requires_all_core_scores(fake_llm):
    bad = structure_reply(scores=scores(names=CORE[:-1] + ["Playfulness"]))
    fake_llm.queue("writer", bad, structure_reply())

    result, _ = coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, None)

    message = last_user_message(fake_llm.requests_for("writer")[1])
    assert "Handling uncertainty" in message
    assert [s["name"] for s in result["scores"]] == CORE
    assert result["comparison"] is None
    schema = fake_llm.requests_for("writer")[0]["payload"]["output_schema"]
    assert schema["properties"]["comparison"] == {"type": "null"}
    assert set(schema["$defs"]["KeyPoint"]["properties"]["line_ids"]["items"]["enum"]) == {"L1", "L2", "L3", "L4"}


def test_scores_must_be_half_steps_in_range(fake_llm):
    fake_llm.queue(
        "writer",
        structure_reply(scores=scores({"Clarity": 7.3})),
        structure_reply(scores=scores({"Overall": 11})),
    )

    with pytest.raises(models.ServiceUnavailable):
        coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, None)

    message = last_user_message(fake_llm.requests_for("writer")[1])
    assert "multiple of 0.5" in message
    score_schema = fake_llm.requests_for("writer")[0]["payload"]["output_schema"]["$defs"]["Score"]
    assert score_schema["properties"]["score"]["enum"] == [i / 2 for i in range(21)]


def test_key_points_cite_only_lines_from_the_analyses(fake_llm):
    bad = structure_reply()
    bad["key_points"][0]["line_ids"] = ["L77"]
    fake_llm.queue("writer", bad, structure_reply())

    coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, None)

    assert "L77" in last_user_message(fake_llm.requests_for("writer")[1])


def test_attempt2_review_requires_comparison_matching_previous_scores(fake_llm):
    previous = {**structure_reply(scores=scores({"Overall": 5.0, "Clarity": 5.5})), "comparison": None}
    new_scores = scores({"Overall": 7.0, "Clarity": 7.5})
    wrong_before = {
        "changes": [{"name": "Overall", "before": 6.0, "after": 7.0}],
        "what_changed": "The example came first.",
    }
    good = {
        "changes": [
            {"name": "Overall", "before": 5.0, "after": 7.0},
            {"name": "Clarity", "before": 5.5, "after": 7.5},
        ],
        "what_changed": "The example came first.",
    }
    fake_llm.queue(
        "writer",
        structure_reply(scores=new_scores, comparison=None),
        structure_reply(scores=new_scores, comparison=wrong_before),
    )
    with pytest.raises(models.ServiceUnavailable):
        coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, previous)
    assert "comparison" in last_user_message(fake_llm.requests_for("writer")[1])

    fake_llm.queue("writer", structure_reply(scores=new_scores, comparison=good))
    result, _ = coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, previous)

    assert result["comparison"]["changes"][0] == {"name": "Overall", "before": 5.0, "after": 7.0}
    request = fake_llm.requests_for("writer")[-1]
    assert request["payload"]["previous_attempt_scores"][0] == {"name": "Overall", "score": 5.0}
    assert "comparison" in request["payload"]["output_schema"]["required"]


def test_too_short_previous_review_needs_no_comparison(fake_llm):
    fake_llm.queue("writer", structure_reply())

    result, _ = coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, {"too_short": True})

    assert result["comparison"] is None


# Review message


REVIEW = {k: v for k, v in structure_reply().items()}


def write_message(note="I rushed the ending."):
    return coach.review_message_pass(LINES, TECHNICAL, COMMUNICATION, TIMING, REVIEW, NOTES, note)


def test_review_message_unknown_markers_stripped(fake_llm):
    fake_llm.queue("writer", 'You said [[L2:"constant time"]] and then [[L99:"made up"]] at the end [[L42]].')

    text, model_used = write_message()

    assert text == 'You said [[L2:"constant time"]] and then  at the end .'
    assert model_used == settings.ollama_model
    assert coach.call_state.warning is None
    request = fake_llm.requests_for("writer")[0]
    assert request["messages"][0]["content"] == coach.MESSAGE_SYSTEM
    assert request["payload"]["learner_note"] == "I rushed the ending."
    assert all("start" not in item for item in request["payload"]["timing"])


@pytest.mark.parametrize("draft", ["At 0:09 you said [[L3]].", "You said [[l3]] about collisions."])
def test_review_message_raw_timestamp_triggers_one_repair(fake_llm, draft):
    fake_llm.queue("writer", draft, "At [[L3]] you described collisions.")

    text, _ = write_message()

    assert text == "At [[L3]] you described collisions."
    assert coach.call_state.warning is None
    repair = fake_llm.requests_for("writer")[1]
    assert repair["payload"]["draft"] == draft
    assert repair["payload"]["line_starts"]["L3"] == "0:09"


def test_review_message_keeps_times_and_warns_when_repair_fails(fake_llm):
    fake_llm.queue("writer", "At 0:09 you said it.", "Still at 0:09 you said it.")

    text, _ = write_message()

    assert text == "Still at 0:09 you said it."
    assert "time" in coach.call_state.warning
    assert len(fake_llm.requests_for("writer")) == 2  # exactly one repair


def test_review_message_truncation_recorded_as_warning(fake_llm):
    fake_llm.queue("writer", Reply("Your answer opened well with [[L1]], and then", "length"))

    text, _ = write_message()

    assert text.endswith("and then")
    assert "cut off" in coach.call_state.warning


def test_review_message_warning_resets_between_calls(fake_llm):
    fake_llm.queue("writer", Reply("Cut", "length"), "A complete review.")
    write_message()
    write_message()
    assert coach.call_state.warning is None


# Payload trimming and short attempts


def test_fit_payload_trims_in_order_and_never_drops_lines(monkeypatch):
    lines = {"L1": "x" * 400}
    payload = {
        "transcript_lines": lines,
        "nuance": "n" * 4000,
        "references": {"practice": "p" * 4000, "hashing_context": "a" * 4000, "collisions_context": "b" * 4000},
    }
    order = ["nuance", "references.practice", "references.hashing_context", "references.collisions_context"]

    monkeypatch.setattr(llm, "prompt_budget", lambda name: 2500)
    fitted = coach.fit_payload("technical", payload, order)
    assert "nuance" not in fitted and "practice" not in fitted["references"]
    assert set(fitted["references"]) == {"hashing_context", "collisions_context"}

    monkeypatch.setattr(llm, "prompt_budget", lambda name: 1500)
    fitted = coach.fit_payload("technical", payload, order)
    assert set(fitted["references"]) == {"collisions_context"}
    assert fitted["transcript_lines"] == lines

    monkeypatch.setattr(llm, "prompt_budget", lambda name: 50)
    with pytest.raises(llm.PromptTooLong):
        coach.fit_payload("technical", payload, order)
    assert payload["nuance"] == "n" * 4000  # the caller's payload is never mutated
    with pytest.raises(ValueError):
        coach.fit_payload("technical", payload, ["transcript_lines"])


def test_fit_payload_shortens_communication_and_writer_fields(monkeypatch):
    monkeypatch.setattr(llm, "prompt_budget", lambda name: 300)
    notes = "## Goals\n" + "g" * 2000 + "\n## Focus areas\n- Lead with an example\n## Struggles\n" + "s" * 2000
    fitted = coach.fit_payload(
        "communication",
        {"transcript_lines": {"L1": "hi"}, "voice_summary": ["One.", "Two.", "Three." * 300], "coach_notes": notes},
        coach.COMMUNICATION_TRIM,
    )
    assert fitted["voice_summary"] == ["One.", "Two."]
    assert fitted["coach_notes"] == "## Focus areas\n- Lead with an example"

    monkeypatch.setattr(llm, "prompt_budget", lambda name: 200)
    payload = {
        "communication": {"points": [{"observation": "o" * 600}, {"observation": "short"}]},
        "technical": {"senior_points": [{"point": "p" * 2000}]},
    }
    fitted = coach.fit_payload("writer", payload, coach.WRITER_TRIM)
    assert len(fitted["communication"]["points"][0]["observation"]) <= 200
    assert fitted["communication"]["points"][1]["observation"] == "short"
    assert "senior_points" not in fitted["technical"]


def test_technical_pass_trims_nuance_before_failing(fake_llm, monkeypatch):
    topic = {**TOPIC, "nuance": "n" * 30000}
    fake_llm.queue("technical", technical_reply(corrections=[]))

    coach.technical_pass(topic, TOPIC["prompt"], LINES)

    assert "nuance" not in fake_llm.requests_for("technical")[0]["payload"]


def test_too_short():
    assert coach.too_short([{"id": "L1", "start": 0, "end": 1, "text": "Testing one two three."}])
    assert not coach.too_short(LINES)


def test_system_prompts_state_one_job():
    for prompt in (coach.TECHNICAL_SYSTEM, coach.COMMUNICATION_SYSTEM, coach.STRUCTURE_SYSTEM, coach.MESSAGE_SYSTEM):
        assert "Your one job" in prompt
    for step in ("learner_note", "Three priorities", "Where the time went", "rewrite", "strong answer", "Next time"):
        assert step in coach.MESSAGE_SYSTEM
    assert json.dumps(coach.MESSAGE_SYSTEM)  # plain text


def test_fake_llm_only_counts_chat_requests(fake_llm):
    fake_llm.queue("technical", technical_reply(corrections=[]))
    assert models.installed_models() == []
    assert fake_llm.requests == [] and len(fake_llm.queues["technical"]) == 1


def test_model_basis_corrections_skip_second_check_and_stay_unverified(fake_llm):
    model_only = [{**c, "basis": "model", "reference_ids": []} for c in corrections("L2", "L4")]

    result = coach.verify_corrections(TOPIC, LINES, model_only)

    assert [(c["line_id"], c["verified"]) for c in result] == [("L2", False), ("L4", False)]
    assert fake_llm.requests == []


def test_only_reference_basis_corrections_are_checked(fake_llm):
    mixed = corrections("L1")
    mixed.append({**corrections("L2")[0], "basis": "model", "reference_ids": []})
    mixed += corrections("L3")
    fake_llm.queue("technical", confirm("C1", "C2"))

    result = coach.verify_corrections(TOPIC, LINES, mixed)

    assert [(c["line_id"], c["verified"]) for c in result] == [("L1", True), ("L2", False), ("L3", True)]
    proposed = fake_llm.requests_for("technical")[0]["payload"]["proposed_corrections"]
    assert [(p["id"], p["line_id"]) for p in proposed] == [("C1", "L1"), ("C2", "L3")]


def test_truncated_draft_keeps_warning_after_marker_repair(fake_llm):
    fake_llm.queue("writer", Reply("At 0:09 you said [[L3]] and then", "length"), "At [[L3]] you said it and then")

    text, _ = write_message()

    assert text == "At [[L3]] you said it and then"
    assert coach.call_state.warning == coach.TRUNCATED_WARNING


def _filler_words(n, seed=0):
    vocab = "the hash function picks a bucket and collisions are compared by key".split()
    return " ".join(vocab[(i + seed) % len(vocab)] for i in range(n))


def test_long_transcript_and_full_notes_fit_the_writer_after_extended_trim(fake_llm):
    """At default limits a 700-word answer plus 390-word notes used to raise PromptTooLong.
    The writer now trims the notes to their focus section, then the concept notes."""
    lines, said = [], 0
    while said < 700:
        lines.append(
            {"id": f"L{len(lines) + 1}", "start": len(lines) * 4.0, "end": len(lines) * 4.0 + 3.5,
             "text": _filler_words(12, said) + "."}
        )
        said += 12
    first = lines[0]["id"]
    technical = {
        "concepts": [
            {"concept_id": f"c{i}", "status": "partial", "line_ids": [first], "note": _filler_words(35, i)}
            for i in range(6)
        ],
        "corrections": [
            {"line_id": first, "claim": _filler_words(25), "correction": _filler_words(40), "basis": "reference",
             "reference_ids": ["c1"], "verified": True}
        ],
        "senior_points": [{"point": _filler_words(35, i), "basis": "model"} for i in range(5)],
    }
    communication = {
        "sections": [{"label": "Whole answer", "first_line": first, "last_line": lines[-1]["id"]}],
        "points": [
            {"kind": "problem", "line_id": first, "observation": _filler_words(55, i), "rewrite": _filler_words(40, i)}
            for i in range(6)
        ],
        "gaps": [{"section_label": "Whole answer", "kind": "communication", "reason": _filler_words(30)}],
        "focus": [{"area": "structure", "observation": _filler_words(45)}],
    }
    review = {
        **structure_reply(),
        "key_points": [{"text": _filler_words(35, i), "line_ids": []} for i in range(3)],
    }
    focus = "## Focus: structure\n" + _filler_words(37)
    notes = (
        focus + "\n## Recurring struggles\n" + _filler_words(150) + "\n## Goals\n" + _filler_words(100)
        + "\n## How they like to be taught\n" + _filler_words(90)
    )
    assert 385 <= len(notes.split()) <= 395
    fake_llm.queue("writer", "A grounded review about [[L1]].")

    text, _model = coach.review_message_pass(lines, technical, communication, [], review, notes, "It went fine.")

    assert text == "A grounded review about [[L1]]."
    sent = fake_llm.requests_for("writer")[0]["payload"]
    assert sent["transcript_lines"] == {line["id"]: line["text"] for line in lines}
    assert sent["coach_notes"] == focus
    assert sent["technical"]["corrections"] == technical["corrections"]


# No model-written clock times in structured fields


def test_technical_pass_repairs_clock_times_in_notes_claims_and_corrections(fake_llm):
    bad = technical_reply()
    bad["concepts"][0]["note"] = "At 0:04 they say the hash picks a bucket."
    bad["corrections"][0]["claim"] = "Around 0:09 they claim colliding keys overwrite."
    bad["corrections"][0]["correction"] = "Unlike what was said at 0:10, both entries are kept."
    fake_llm.queue("technical", bad, technical_reply(), confirm("C1"))

    result, _ = coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)

    message = last_user_message(fake_llm.requests_for("technical")[1])
    assert "concepts[hashing].note" in message
    assert "corrections[0].claim" in message and "corrections[0].correction" in message
    assert result["concepts"][0]["note"] == "Hash picks a bucket."


def test_technical_pass_fails_when_clock_times_survive_the_repair(fake_llm):
    bad = technical_reply(corrections=[])
    bad["concepts"][0]["note"] = "At 0:04 they say the hash picks a bucket."
    fake_llm.queue("technical", bad, bad)

    with pytest.raises(models.ServiceUnavailable):
        coach.technical_pass(TOPIC, TOPIC["prompt"], LINES)


def test_communication_pass_repairs_clock_times_in_observations(fake_llm):
    bad = communication_reply()
    bad["points"][0]["observation"] = "At 0:00 you open with a plain definition."
    bad["focus"][0]["observation"] = "The example only came at 0:15."
    fake_llm.queue("communication", bad, communication_reply())

    result, _ = coach.communication_pass(LINES, VOICE, NOTES, {"prompt": TOPIC["prompt"], "duration": 21.0})

    message = last_user_message(fake_llm.requests_for("communication")[1])
    assert "points[0].observation" in message and "focus[0].observation" in message
    assert result["points"][0]["observation"] == "Opens with a plain definition."


def test_review_structure_repairs_clock_times_in_every_written_field(fake_llm):
    previous = {**structure_reply(), "comparison": None}
    bad = structure_reply(
        comparison={
            "changes": [{"name": "Overall", "before": 6.5, "after": 6.5}],
            "what_changed": "This time the example came at 0:20 instead of 1:05.",
        }
    )
    bad["scores"][1]["reason"] = "Clear until 0:09."
    bad["key_points"][0]["text"] = "Collisions are misstated at 0:09."
    bad["checklist"][0] = "Reach the example before 0:30."
    good = structure_reply(
        comparison={"changes": [{"name": "Overall", "before": 6.5, "after": 6.5}], "what_changed": "Example first."}
    )
    fake_llm.queue("writer", bad, good)

    result, _ = coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, previous)

    message = last_user_message(fake_llm.requests_for("writer")[1])
    for field in ("scores[1].reason", "key_points[0].text", "checklist[0]", "comparison.what_changed"):
        assert field in message
    assert result["checklist"][0] == "Open with the word-count example."


def test_second_check_correction_with_a_clock_time_keeps_the_original(fake_llm):
    reply = confirm("C1")
    reply["reviews"][0]["correction"] = "What was said at 0:10 is wrong: both entries are kept."
    fake_llm.queue("technical", reply)

    [result] = coach.verify_corrections(TOPIC, LINES, corrections("L3"))

    assert result["verified"] is True and result["correction"] == "Correction for L3."


def test_writer_prompts_act_on_question_change():
    """The angle-change signal is data in the payload; both writer system prompts say what to do with it."""
    for system in (coach.STRUCTURE_SYSTEM, coach.MESSAGE_SYSTEM):
        assert "question_change" in system
        assert "indicative" in system


def test_knowledge_check_uses_full_answer_and_removes_contradicted_feedback(fake_llm):
    communication = communication_reply()
    fake_llm.queue("technical", {
        "verdicts": [{"gap_id": "G0", "kind": "communication", "reason": "The example clarifies the mechanism.",
                      "evidence": ["L4"]}],
        "withdraw_points": [1],
    })
    checked = coach.check_coaching_findings(communication, TOPIC, TOPIC["prompt"], LINES)
    assert checked["gaps"][0]["kind"] == "communication"
    assert checked["gaps"][0]["line_ids"] == ["L4"]
    assert checked["points"] == communication["points"][:1]
    assert checked["gap_check"]["model"]
    call = fake_llm.requests_for("technical")[0]["payload"]
    assert list(call["transcript_lines"]) == [line["id"] for line in LINES]
    assert call["references"]["collisions"] == coach.references(TOPIC)["collisions"]


def test_knowledge_check_degrades_to_question_if_verdict_cannot_be_validated(fake_llm):
    bad = {"verdicts": [{"gap_id": "G0", "kind": "knowledge", "reason": "Overwrites.", "evidence": ["L999"]}],
           "withdraw_points": []}
    fake_llm.queue("technical", bad, bad)
    checked = coach.check_coaching_findings(communication_reply(), TOPIC, TOPIC["prompt"], LINES)
    assert checked["gaps"][0]["kind"] == "unclear"
    assert checked["gap_check"]["status"] == "unavailable"
    assert checked["points"] == communication_reply()["points"]


def test_no_knowledge_gap_needs_no_check(fake_llm):
    communication = communication_reply(gaps=[], points=[])
    assert coach.check_coaching_findings(communication, TOPIC, TOPIC["prompt"], LINES) == communication
    assert not fake_llm.requests


def test_generation_schema_requires_a_rewrite_only_for_problems(fake_llm):
    fake_llm.queue("communication", communication_reply())
    coach.communication_pass(LINES, VOICE, NOTES, {"prompt": TOPIC["prompt"], "duration": 21})
    defs = fake_llm.requests_for("communication")[0]["body"]["format"]["$defs"]
    assert defs["CommunicationStrength"]["properties"]["rewrite"]["const"] == ""
    assert defs["CommunicationProblem"]["properties"]["rewrite"]["minLength"] == 1


def test_accuracy_is_unscored_without_an_assessed_claim(fake_llm):
    technical = {**TECHNICAL, "corrections": [], "concepts": [{**c, "status": "missing", "line_ids": []}
                                                            for c in TECHNICAL["concepts"]]}
    remaining = [name for name in CORE if name != "Technical accuracy"]
    fake_llm.queue("writer", structure_reply(scores=scores(names=remaining), key_points=[
        {"text": "Teach one mechanism.", "line_ids": []} for _ in range(3)
    ]))
    review, _ = coach.review_structure_pass(technical, COMMUNICATION, TIMING, NOTES, None, None)
    assert "Too little technical evidence" in review["accuracy_unscored"]
    assert [s["name"] for s in review["scores"]] == remaining


def test_comparison_schema_excludes_previously_unscored_dimensions(fake_llm):
    previous = {"scores": scores(names=["Overall"])}
    change = {"name": "Overall", "before": 6.5, "after": 6.5}
    fake_llm.queue("writer", structure_reply(comparison={"changes": [change], "what_changed": "A new example."}))
    coach.review_structure_pass(TECHNICAL, COMMUNICATION, TIMING, NOTES, None, previous)
    defs = fake_llm.requests_for("writer")[0]["body"]["format"]["$defs"]
    assert defs["ScoreChange"]["properties"]["name"]["enum"] == ["Overall"]
