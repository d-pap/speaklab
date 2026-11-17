"""Coach chat: context building, running summary, streaming endpoint and its gates."""

import json

import httpx
import pytest
from conftest import MINIMAL_CHAT_REPLY, MINIMAL_CHAT_SUMMARY, MINIMAL_REVIEW, create, upload

from app import chat, db, llm, main


def ready(client, wav_bytes):
    """Attempt 1 recorded, note skipped, review written: the chat is open."""
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    response = client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    assert response.status_code == 200, response.text
    return db.one("SELECT * FROM sessions WHERE id=?", (session["id"],)), db.one(
        "SELECT * FROM attempts WHERE id=?", (attempt["id"],)
    )


def add_turns(session_id, contents, attempt_number=1):
    ids = []
    with db.connect() as conn:
        for i, text in enumerate(contents):
            cursor = conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind) VALUES(?,?,?,?,?,?)",
                (session_id, "user" if i % 2 == 0 else "assistant", text, db.now(), attempt_number, "chat"),
            )
            ids.append(cursor.lastrowid)
    return ids


def send(client, session_id, message="Explain collisions", attempt_number=1):
    return client.post(
        f"/api/sessions/{session_id}/chat", json={"message": message, "attempt_number": attempt_number}
    )


def events(response):
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def ndjson(*chunks, done_reason="stop"):
    lines = [{"message": {"role": "assistant", "content": c}, "done": False} for c in chunks]
    lines.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason})
    return httpx.Response(200, content="\n".join(json.dumps(line) for line in lines) + "\n")


def chat_messages(session_id):
    return db.all_rows("SELECT * FROM messages WHERE session_id=? AND kind='chat' ORDER BY id", (session_id,))


def test_context_keeps_review_transcript_and_notes_when_summarized(client, wav_bytes):
    session, attempt = ready(client, wav_bytes)
    db.execute(
        "INSERT INTO coach_notes(created_at,content,source) VALUES(?,?,?)",
        (db.now(), "## Focus: pacing\nNotes about the learner.", "learner"),
    )
    ids = add_turns(session["id"], ["old question", "old answer", "recent question", "recent answer"])
    db.execute(
        "UPDATE attempts SET chat_summary=?, chat_summary_through=? WHERE id=?",
        ("They asked about buckets.", ids[1], attempt["id"]),
    )
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    history = chat.unsummarized_turns(attempt)
    messages = chat.build_context(session, attempt, history, llm.prompt_budget("chat"))

    assert messages[0] == {"role": "system", "content": chat.CHAT_SYSTEM}
    context = messages[1]
    assert context["role"] == "system"
    text = context["content"]
    analysis = json.loads(attempt["analysis"])
    order = [
        text.index("Notes about the learner."),
        text.index("L1: A hash map stores keys and values."),
        text.index(analysis["review"]["checklist"][0]),
        text.index("Senior point 1."),
        text.index("Whole answer"),
        text.index("## Topic reference"),
    ]
    assert order == sorted(order)
    assert messages[2] == {"role": "assistant", "content": MINIMAL_REVIEW}
    assert messages[3]["role"] == "system" and "They asked about buckets." in messages[3]["content"]
    assert [(m["role"], m["content"]) for m in messages[4:]] == [
        ("user", "recent question"),
        ("assistant", "recent answer"),
    ]
    assert "old question" not in json.dumps(messages)


def test_summary_triggers_over_75_percent_budget_and_keeps_last_four_turns(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    budget = llm.prompt_budget("chat")
    small = [{"role": "user", "content": "x" * (budget * 4 * 70 // 100)}]
    large = [{"role": "user", "content": "x" * (budget * 4 * 80 // 100)}]
    assert not chat.needs_summary(small, budget)
    assert chat.needs_summary(large, budget)

    contents = [f"turn {n} " + "word " * 200 for n in range(20)]
    ids = add_turns(session["id"], contents)
    response = send(client, session["id"], "What should I learn next?")
    assert response.status_code == 200, response.text
    assert events(response)[-1]["done"] is True

    summary_calls = [r for r in fake_llm.requests_for("chat") if not r["body"]["stream"]]
    [summary_call] = summary_calls
    folded = [turn["content"] for turn in summary_call["payload"]["turns"]]
    assert folded == contents[:17]  # 20 stored + the new question; the latest 4 stay as turns
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert attempt["chat_summary"] == MINIMAL_CHAT_SUMMARY
    assert attempt["chat_summary_through"] == ids[16]
    assert attempt["chat_summary_model"] == llm.pass_settings()["chat"]["model"]  # provenance

    [reply_call] = [r for r in fake_llm.requests_for("chat") if r["body"]["stream"]]
    sent = reply_call["messages"]
    assert sent[2] == {"role": "assistant", "content": MINIMAL_REVIEW}  # never summarized away
    assert MINIMAL_CHAT_SUMMARY in sent[3]["content"]
    assert [m["content"] for m in sent[4:]] == [*contents[17:], "What should I learn next?"]


def test_summary_failure_still_replies(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    add_turns(session["id"], [f"turn {n} " + "word " * 200 for n in range(20)])
    fake_llm.queue("chat", httpx.ConnectError("down"), "Still answering.")
    response = send(client, session["id"])
    assert events(response)[-1]["message"]["content"] == "Still answering."
    assert db.one("SELECT chat_summary FROM attempts WHERE id=?", (attempt["id"],))["chat_summary"] is None


def test_chat_streams_deltas_then_done_with_parts(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    fake_llm.queue("chat", ndjson("You said ", "[[L1]]", " clearly."))
    response = send(client, session["id"], "  How did my opening go?  ")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    received = events(response)
    assert [e["delta"] for e in received[:-1]] == ["You said ", "[[L1]]", " clearly."]
    done = received[-1]
    assert done["done"] is True and "warning" not in done
    message = done["message"]
    assert message["role"] == "assistant" and message["kind"] == "chat" and message["attempt_number"] == 1
    assert message["content"] == "You said [[L1]] clearly."
    assert message["model"]
    assert message["parts"][1] == {"type": "ref", "line_id": "L1", "start": 0.0, "quote": ""}

    stored = chat_messages(session["id"])
    assert [(m["role"], m["content"]) for m in stored] == [
        ("user", "How did my opening go?"),
        ("assistant", "You said [[L1]] clearly."),
    ]
    detail = client.get(f"/api/sessions/{session['id']}").json()
    assert [m["kind"] for m in detail["messages"]] == ["review", "chat", "chat"]
    assert detail["messages"][-1]["parts"] == message["parts"]


def test_chat_reply_unknown_markers_stripped(client, wav_bytes, fake_llm):
    session, _attempt = ready(client, wav_bytes)
    fake_llm.queue("chat", ndjson("See [[L1]] and [[L99]]", " for that."))
    message = events(send(client, session["id"]))[-1]["message"]
    assert message["content"] == "See [[L1]] and  for that."
    assert [p["line_id"] for p in message["parts"] if p["type"] == "ref"] == ["L1"]


def test_truncated_reply_is_kept_with_a_warning(client, wav_bytes, fake_llm):
    session, _attempt = ready(client, wav_bytes)
    fake_llm.queue("chat", ndjson("A long answer that", done_reason="length"))
    done = events(send(client, session["id"]))[-1]
    assert done["message"]["content"] == "A long answer that"
    assert "cut off" in done["warning"]


def test_chat_refused_while_analysis_running(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    # The note box is still open, so the writer is waiting.
    response = send(client, session["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "The coach is still reviewing this attempt."

    analysis = json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (attempt["id"],))["analysis"])
    for status, writer in (("processing", "waiting"), ("pending", "done"), ("ready", "pending"), ("ready", "running")):
        analysis["passes"]["writer"]["status"] = writer
        db.execute(
            "UPDATE attempts SET status=?, analysis=? WHERE id=?", (status, json.dumps(analysis), attempt["id"])
        )
        assert send(client, session["id"]).status_code == 409, (status, writer)
    assert fake_llm.requests_for("chat") == []
    assert chat_messages(session["id"]) == []


def set_passes(attempt_id, status, **passes):
    analysis = json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (attempt_id,))["analysis"])
    for name, pass_status in passes.items():
        analysis["passes"][name]["status"] = pass_status
    db.execute("UPDATE attempts SET status=?, analysis=? WHERE id=?", (status, json.dumps(analysis), attempt_id))


def test_chat_blocked_while_writer_waits_for_note(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (attempt["id"],))["analysis"])[
        "passes"
    ]["writer"]["status"] == "waiting"
    assert send(client, session["id"]).status_code == 409
    assert fake_llm.requests_for("chat") == []


def test_chat_blocked_while_writer_queued_after_phase_one(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    set_passes(attempt["id"], "ready", writer="pending")
    response = send(client, session["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == chat.REVIEWING


def test_chat_allowed_when_communication_pass_failed(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    # Phase 1 failed, so the writer stays pending with no review on its way.
    set_passes(attempt["id"], "partial", communication="failed", writer="pending")
    response = send(client, session["id"])
    assert response.status_code == 200, response.text
    assert events(response)[-1]["done"] is True


def test_chat_allowed_when_attempt_interrupted_mid_write(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    # A restart during the writer: status interrupted, the stored writer still says running.
    set_passes(attempt["id"], "interrupted", writer="running")
    response = send(client, session["id"])
    assert response.status_code == 200, response.text
    assert events(response)[-1]["done"] is True


def test_chat_allowed_when_writer_failed(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    analysis = json.loads(attempt["analysis"])
    analysis["passes"]["writer"] = {"status": "failed", "model": None, "error": "Writer broke."}
    analysis["passes"]["communication"]["status"] = "done"
    analysis["review"] = None
    analysis["communication"] = None
    db.execute(
        "UPDATE attempts SET status='partial', analysis=? WHERE id=?", (json.dumps(analysis), attempt["id"])
    )
    response = send(client, session["id"])
    assert response.status_code == 200
    assert events(response)[-1]["message"]["content"] == MINIMAL_CHAT_REPLY
    context = fake_llm.requests_for("chat")[-1]["messages"][1]["content"]
    assert "Senior point 1." in context  # the technical analysis that exists is still used


def test_chat_allowed_for_too_short_attempt(client, wav_bytes, fake_llm, monkeypatch):
    from app import models

    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Testing one two.", []))
    session = create(client)
    upload(client, session, wav_bytes)
    response = send(client, session["id"])
    assert response.status_code == 200, response.text
    assert events(response)[-1]["done"] is True


def test_parallel_chat_refused(client, wav_bytes, fake_llm):
    session, _attempt = ready(client, wav_bytes)
    with main.tutor_lock:
        response = send(client, session["id"])
    assert response.status_code == 409
    assert "already answering" in response.json()["detail"]
    # The lock is released after a normal reply and after a failed one.
    assert events(send(client, session["id"]))[-1]["done"] is True
    fake_llm.queue("chat", httpx.ConnectError("down"))
    failed = events(send(client, session["id"]))
    assert list(failed[-1]) == ["error"]
    assert events(send(client, session["id"]))[-1]["done"] is True


def test_attempt_two_chat_refused_before_it_exists(client, wav_bytes, fake_llm):
    session, _attempt = ready(client, wav_bytes)
    response = send(client, session["id"], attempt_number=2)
    assert response.status_code == 409
    assert "attempt 2" in response.json()["detail"].lower()
    assert send(client, session["id"], attempt_number=3).status_code == 422
    assert send(client, session["id"], message="   ").status_code == 422
    assert fake_llm.requests_for("chat") == []


def test_failed_reply_keeps_question_without_assistant_row(client, wav_bytes, fake_llm):
    session, _attempt = ready(client, wav_bytes)
    fake_llm.queue("chat", httpx.ConnectError("down"))
    failed = events(send(client, session["id"], "First question"))
    assert "error" in failed[-1]
    # The question stays; no assistant row is written for a failed reply.
    assert [(m["role"], m["content"]) for m in chat_messages(session["id"])] == [("user", "First question")]


def test_context_fits_prompt_budget(client, wav_bytes):
    session, attempt = ready(client, wav_bytes)
    add_turns(session["id"], [f"turn {n} " + "word " * 160 for n in range(60)])
    history = chat.unsummarized_turns(db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],)))
    assert len(history) == 60
    budget = llm.prompt_budget("chat")
    messages = chat.build_context(session, attempt, history, budget)
    assert llm._estimate_tokens(messages) <= budget
    assert messages[-1]["content"] == history[-1]["content"]
    assert messages[2] == {"role": "assistant", "content": MINIMAL_REVIEW}
    assert 1 < len(messages) - 3 < 60  # older turns dropped, the latest kept
    assert "L1: " in messages[1]["content"]


def test_replaced_attempt_drops_its_chat(client, wav_bytes, fake_llm):
    session = create(client)
    first = upload(client, session, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    db.execute("UPDATE sessions SET stage='record2' WHERE id=?", (session["id"],))
    second = upload(client, session, wav_bytes, 2)
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    assert send(client, session["id"], "About attempt one").status_code == 200
    assert send(client, session["id"], "About attempt two", attempt_number=2).status_code == 200
    db.execute(
        "UPDATE attempts SET chat_summary='old summary', chat_summary_through=99 WHERE id=?", (second["id"],)
    )

    # Attempt 2's review completed the session; reopen it as if that review had not finished.
    db.execute("UPDATE sessions SET stage='record2', completed_at=NULL WHERE id=?", (session["id"],))
    replaced = upload(client, session, wav_bytes, 2)
    remaining = [(m["attempt_number"], m["content"]) for m in chat_messages(session["id"])]
    assert remaining == [(1, "About attempt one"), (1, MINIMAL_CHAT_REPLY)]
    row = db.one("SELECT chat_summary, chat_summary_through FROM attempts WHERE id=?", (replaced["id"],))
    assert row == {"chat_summary": None, "chat_summary_through": 0}


def test_old_tutor_and_lesson_endpoints_are_gone(client, wav_bytes):
    session, _attempt = ready(client, wav_bytes)
    assert client.get(f"/api/sessions/{session['id']}/lesson").status_code in (404, 405)
    assert client.post(f"/api/sessions/{session['id']}/tutor", json={"message": "hi"}).status_code in (404, 405)


def test_context_includes_review_message_as_first_assistant_turn(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    add_turns(session["id"], ["Why structure?", "Because it guides the listener."])
    db.execute(
        "UPDATE attempts SET chat_summary='Earlier they asked about pacing.' WHERE id=?", (attempt["id"],)
    )
    response = send(client, session["id"], "Explain the example answer you gave")
    assert response.status_code == 200
    sent = fake_llm.requests_for("chat")[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "system", "assistant", "system", "user", "assistant", "user"]
    assert sent[2]["content"] == MINIMAL_REVIEW
    assert "Earlier they asked about pacing." in sent[3]["content"]
    assert sent[-1]["content"] == "Explain the example answer you gave"


LONG_REVIEW = "\n\n".join(
    [
        "## Your read\nREVIEW-OPENING you were right that the middle dragged.",
        "## Three priorities\n" + "priority detail " * 120,
        "## Moments\n" + "moment detail " * 120,
        "## A strong answer\nSTRONG-ANSWER A hash map turns a key into a bucket index.",
        "## Next time\n" + "next detail " * 40,
    ]
)


def test_context_trims_reference_then_analyses_then_review_prose(client, wav_bytes):
    session, attempt = ready(client, wav_bytes)
    lines = [{"id": f"L{i}", "text": f"LINE-{i} " + "speak " * 13, "start": i * 5.0} for i in range(1, 51)]
    analysis = json.loads(attempt["analysis"])
    analysis["technical"]["corrections"] = [
        {"line_id": "L3", "claim": "CLAIM-MARK", "correction": "Fix it.", "basis": "reference", "reference_ids": []}
    ]
    db.execute(
        "UPDATE attempts SET lines=?, analysis=? WHERE id=?", (json.dumps(lines), json.dumps(analysis), attempt["id"])
    )
    db.execute("UPDATE messages SET content=? WHERE kind='review'", (LONG_REVIEW,))
    db.execute(
        "INSERT INTO coach_notes(created_at,content,source) VALUES(?,?,?)",
        (db.now(), "NOTES-MARK " + "note " * 390, "learner"),
    )
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    history = [{"role": "user", "content": "What next?"}]

    def state(messages):
        context, review = messages[1]["content"], messages[2]["content"]
        # Notes, every transcript line, the review structure and the review's opening always stay.
        assert "NOTES-MARK" in context and all(f"LINE-{i} " in context for i in range(1, 51))
        assert analysis["review"]["checklist"][0] in context
        assert "REVIEW-OPENING" in review and "STRONG-ANSWER" in review
        assert "CLAIM-MARK" in context  # corrections outlive the rest of the technical analysis
        return (
            '"core"' in context,  # the topic reference
            "Whole answer" in context,  # the communication analysis
            "Senior point 1." in context,  # the technical analysis beyond its corrections
            "priority detail" in review,  # the review's middle
        )

    full = chat.build_context(session, attempt, history, 10**6)
    states = [state(full)]
    budget = llm._estimate_tokens(full)
    while True:
        budget -= 25
        try:
            messages = chat.build_context(session, attempt, history, budget)
        except llm.PromptTooLong:
            break
        assert llm._estimate_tokens(messages) <= budget
        if state(messages) != states[-1]:
            states.append(state(messages))
    assert states == [
        (True, True, True, True),
        (False, True, True, True),
        (False, False, True, True),
        (False, False, False, True),
        (False, False, False, False),
    ]
    shortened = chat.shorten_review(LONG_REVIEW)
    assert chat.REVIEW_GAP in shortened and "Next time" not in shortened
    assert shortened.endswith("STRONG-ANSWER A hash map turns a key into a bucket index.")


@pytest.mark.parametrize("text", ["Short review.", "## Opening\n" + "words " * 400])
def test_shorten_review_without_strong_answer_keeps_opening(text):
    shortened = chat.shorten_review(text)
    assert shortened.startswith(text[:10])
    assert len(shortened) <= chat.REVIEW_OPENING_CHARS + len(chat.REVIEW_GAP) + 2


def test_running_summary_records_the_model_that_wrote_it(client, wav_bytes, fake_llm):
    session, attempt = ready(client, wav_bytes)
    db.execute("INSERT INTO app_settings(key,value) VALUES('pass.chat.model','chosen-chat:1b')")
    turns = add_turns(session["id"], ["first turn", "second turn"])
    chat.summarize(attempt["id"], db.all_rows("SELECT * FROM messages WHERE id IN (?,?)", tuple(turns)))
    row = db.one("SELECT chat_summary, chat_summary_model FROM attempts WHERE id=?", (attempt["id"],))
    assert row == {"chat_summary": MINIMAL_CHAT_SUMMARY, "chat_summary_model": "chosen-chat:1b"}
