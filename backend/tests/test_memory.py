import json
import uuid

import httpx
import pytest
from conftest import Reply

from app import db, memory

OLD_NOTES = (
    "## Focus: natural playfulness\n"
    "Since 2026-11-01. Wants answers to sound less rehearsed.\n"
    "## Focus: structure\n"
    "Since 2026-11-03. Opens without a definition.\n"
    "## Goals\n"
    "- Senior-level system design answers."
)
DROPPED_PLAYFULNESS = (
    "## Focus: structure\n"
    "Since 2026-11-03. Now opens with a definition; next, signpost the sections.\n"
    "## Goals\n"
    "- Senior-level system design answers.\n"
    "## How they like to be taught\n"
    "- Wants the senior-engineer answer first."
)


@pytest.fixture
def notes_db(fake_llm):
    db.initialize()
    return fake_llm


def add_reviewed_attempt(
    created="2026-11-10T10:00:00+00:00",
    chat=(("user", "I'm working on keeping things light."), ("assistant", "A light opener can help.")),
    note="I rushed the ending.",
    review_message=True,
):
    session_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    review = {
        "scores": [{"name": "Overall", "score": 6.0, "reason": "Clear start, rushed end."}],
        "key_points": [{"text": "The definition landed in the first line.", "line_ids": ["L1"]}],
        "checklist": ["Close with a summary."],
        "comparison": None,
    }
    lines = [{"id": "L1", "start": 0.0, "end": 3.0, "text": "A hash map maps keys to values."}]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind) VALUES(?,?,?,?,?,?)",
            (session_id, "hash-maps", created, 120, "Conversational", "Concept explanation"),
        )
        conn.execute(
            "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,"
            "transcript,lines,analysis,learner_note,note_state,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                session_id,
                1,
                created,
                "a.wav",
                "a.decoded.wav",
                "audio/wav",
                3.0,
                lines[0]["text"],
                json.dumps(lines),
                json.dumps({"review": review}),
                note,
                "submitted" if note else "skipped",
                "ready",
            ),
        )
        rows = [("assistant", "Your review. [[L1]]", "review")] if review_message else []
        rows += [(role, text, "chat") for role, text in chat]
        for role, text, kind in rows:
            conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind) VALUES(?,?,?,?,?,?)",
                (session_id, role, text, created, 1, kind),
            )
    return attempt_id


def test_memory_versions_and_restore(notes_db):
    assert memory.current_notes() == {"id": None, "content": "", "model": None}
    assert memory.versions() == []
    first = memory.save_learner_edit("## Focus: structure\nOpen with a definition.")
    second = memory.save_learner_edit("## Focus: pacing\nSlow down in the middle.")
    assert first["source"] == second["source"] == "learner"
    assert memory.current_notes() == {"id": second["id"], "content": second["content"], "model": None}
    restored = memory.restore(first["id"])
    assert restored["source"] == "restore" and restored["model"] is None
    assert restored["content"] == first["content"]
    assert memory.current_notes()["content"] == first["content"]
    assert [v["id"] for v in memory.versions()] == [restored["id"], second["id"], first["id"]]
    assert memory.versions()[0]["folded_attempt_ids"] == []
    with pytest.raises(LookupError):
        memory.restore(9999)


def test_learner_edit_over_400_words_rejected(notes_db):
    memory.save_learner_edit("Short notes.")
    with pytest.raises(ValueError, match="400 words"):
        memory.save_learner_edit("word " * 401)
    assert memory.current_notes()["content"] == "Short notes."
    assert len(memory.versions()) == 1
    assert memory.save_learner_edit("word " * 400)["content"]


def test_unfolded_attempts_need_a_review_and_stay_folded(notes_db):
    reviewed = add_reviewed_attempt()
    add_reviewed_attempt(review_message=False)
    items = memory.unfolded_attempts()
    assert [item["id"] for item in items] == [reviewed]
    item = items[0]
    assert item["lines"][0]["id"] == "L1"
    assert item["review"]["key_points"][0]["text"].startswith("The definition")
    assert item["learner_note"] == "I rushed the ending."
    assert [m["role"] for m in item["messages"]] == ["user", "assistant"]
    notes_db.queue("memory", "## Focus: keeping things light\nSince 2026-11-10.")
    result = memory.fold_in()
    assert result["folded_attempt_ids"] == [reviewed]
    assert memory.unfolded_attempts() == []
    memory.save_learner_edit("Learner rewrite.")  # an edit doesn't unfold anything
    assert memory.unfolded_attempts() == []
    assert memory.fold_in() is None and memory.call_state.error is None


def test_fold_in_sends_compact_digest_with_learner_messages_only(notes_db):
    memory.save_learner_edit(OLD_NOTES)
    attempt = add_reviewed_attempt()
    notes_db.queue("memory", OLD_NOTES + "\n- Wants to keep things light.")
    result = memory.fold_in()
    assert result["source"] == "memory" and result["model"]
    assert memory.versions()[0]["folded_attempt_ids"] == [attempt]
    assert memory.versions()[0]["model"] == result["model"] == memory.current_notes()["model"]
    payload = notes_db.requests_for("memory")[0]["payload"]
    assert payload["current_notes"] == OLD_NOTES
    digest = payload["attempts"][0]
    assert digest["learner_messages"] == ["I'm working on keeping things light."]
    assert digest["learner_note"] == "I rushed the ending."
    assert digest["key_points"] == ["The definition landed in the first line."]
    assert digest["scores"] == [{"name": "Overall", "score": 6.0}]
    assert "A light opener can help." not in json.dumps(payload)
    assert "transcript" not in json.dumps(payload).lower()


def test_fold_in_keeps_focus_area_the_model_dropped(notes_db):
    memory.save_learner_edit(OLD_NOTES)
    add_reviewed_attempt()
    notes_db.queue("memory", DROPPED_PLAYFULNESS, DROPPED_PLAYFULNESS)
    result = memory.fold_in()
    requests = notes_db.requests_for("memory")
    assert len(requests) == 2  # one repair, naming the dropped heading
    assert "## Focus: natural playfulness" in requests[1]["messages"][-1]["content"]
    content = memory.current_notes()["content"]
    assert result["content"] == content
    assert content.startswith(DROPPED_PLAYFULNESS)
    assert "## Focus: natural playfulness\nSince 2026-11-01. Wants answers to sound less rehearsed." in content


def test_fold_in_repairs_notes_over_400_words_once(notes_db):
    memory.save_learner_edit(OLD_NOTES)
    add_reviewed_attempt()
    notes_db.queue("memory", OLD_NOTES + "\n" + "word " * 400, OLD_NOTES + "\n- Shorter now.")
    result = memory.fold_in()
    assert result["content"].endswith("- Shorter now.")
    repair = notes_db.requests_for("memory")[1]["messages"][-1]["content"]
    assert "400 words" in repair


def test_fold_in_failure_leaves_notes_unchanged(notes_db):
    memory.save_learner_edit(OLD_NOTES)
    attempt = add_reviewed_attempt()
    before = memory.versions()
    notes_db.queue("memory", httpx.ConnectError("offline"))
    assert memory.fold_in() is None
    assert memory.call_state.error
    assert memory.versions() == before
    assert [item["id"] for item in memory.unfolded_attempts()] == [attempt]
    # Still over the cap after the one repair: a failure, not a longer note.
    notes_db.queue("memory", "word " * 401, Reply("word " * 380, "length"))
    assert memory.fold_in() is None
    assert "400 words" in memory.call_state.error
    assert memory.versions() == before


def test_fold_in_folds_the_oldest_batch_that_fits(notes_db, monkeypatch):
    first = add_reviewed_attempt(created="2026-11-01T10:00:00+00:00", chat=[("user", "a" * 500)] * 12)
    second = add_reviewed_attempt(created="2026-11-02T10:00:00+00:00", chat=[("user", "b" * 500)] * 12)
    monkeypatch.setattr(memory, "_budget", lambda: memory._estimate(memory._payload("", [])) + 2600)
    notes_db.queue("memory", "## Focus: structure\nSince 2026-11-01.")
    result = memory.fold_in()
    assert result["folded_attempt_ids"] == [first]
    assert [item["id"] for item in memory.unfolded_attempts()] == [second]


def test_coach_notes_api_edit_and_restore(client):
    assert client.get("/api/coach-notes").json() == {
        "current": {"id": None, "content": "", "model": None},
        "versions": [],
    }
    first = client.put("/api/coach-notes", json={"content": "## Focus: structure\nOpen with a definition."})
    assert first.status_code == 200
    first_version = first.json()["versions"][0]
    assert first_version["source"] == "learner"
    second = client.put("/api/coach-notes", json={"content": "## Focus: pacing\nSlow down."}).json()
    second_version = second["versions"][0]
    body = client.get("/api/coach-notes").json()
    assert body == second
    assert body["current"] == {"id": second_version["id"], "content": second_version["content"], "model": None}
    assert [v["id"] for v in body["versions"]] == [second_version["id"], first_version["id"]]

    too_long = client.put("/api/coach-notes", json={"content": "word " * 401})
    assert too_long.status_code == 422 and "400 words" in too_long.json()["detail"]
    assert len(client.get("/api/coach-notes").json()["versions"]) == 2

    restored = client.post(f"/api/coach-notes/{first_version['id']}/restore")
    assert restored.status_code == 200 and restored.json()["versions"][0]["source"] == "restore"
    assert restored.json() == client.get("/api/coach-notes").json()
    assert restored.json()["current"]["content"] == first_version["content"]
    assert client.post("/api/coach-notes/9999/restore").status_code == 404


def test_coach_notes_save_and_restore_return_the_same_shape_as_get(client):
    """The settings panel replaces its whole view with the response; a bare version row blanks it."""
    saved = client.put("/api/coach-notes", json={"content": "## Focus: structure\nOpen with a definition."})
    assert set(saved.json()) == {"current", "versions"}
    assert set(saved.json()["current"]) == {"id", "content", "model"}
    restored = client.post(f"/api/coach-notes/{saved.json()['current']['id']}/restore")
    assert set(restored.json()) == {"current", "versions"}
    assert saved.json()["versions"][0].keys() == restored.json()["versions"][0].keys()


def test_fold_discarded_when_notes_edited_during_the_model_call(notes_db):
    memory.save_learner_edit(OLD_NOTES)
    attempt = add_reviewed_attempt()

    def edit_midway(record):
        memory.save_learner_edit("## Focus: pacing\nThe learner's own rewrite.")
        return OLD_NOTES + "\n- Wants to keep things light."

    notes_db.queue("memory", edit_midway)
    assert memory.fold_in() is None
    assert "changed while" in memory.call_state.error
    assert memory.current_notes()["content"] == "## Focus: pacing\nThe learner's own rewrite."
    assert [v["source"] for v in memory.versions()] == ["learner", "learner"]  # nothing saved over the edit
    assert [item["id"] for item in memory.unfolded_attempts()] == [attempt]  # the next fold picks it up
    notes_db.queue("memory", "## Focus: pacing\nThe learner's own rewrite.\n- Wants to keep things light.")
    assert memory.fold_in()["folded_attempt_ids"] == [attempt]


def test_fold_discarded_pass_is_recorded_as_failed_memory_pass(client, wav_bytes, fake_llm):
    from conftest import upload

    first = upload(client, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})

    def edit_midway(record):
        memory.save_learner_edit("## Focus: pacing\nEdited during the update.")
        return "## Focus: structure\nSince the first session."

    fake_llm.queue("memory", edit_midway)
    second = upload(client, wav_bytes, "caching")
    entry = second["analysis"]["passes"]["memory"]
    assert entry["status"] == "failed" and "changed while" in entry["error"]
    assert memory.current_notes()["content"] == "## Focus: pacing\nEdited during the update."
