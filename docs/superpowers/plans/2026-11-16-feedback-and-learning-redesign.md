# Feedback and Learning Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SpeakLab's rubric report and prewritten lessons with a review page: a CapCut-style transcript, a fixed Review tab and a coach chat. It is backed by separate local model passes and plain-text coach notes, and attempt 2 moves to a later day.

**Architecture:** Every model call goes through a new `llm.py` boundary keyed by pass name, so each pass has its own model and limits and tests can double every call in one place.
- **Pipeline phase 1:** measurements and transcript lines (code), then the technical pass and the communication pass.
- **Pipeline phase 2:** the coach-notes memory pass, the review-structure pass and the review-message pass. It starts once the learner submits or skips their note, or after a timeout.
- **Chat:** replies stream over Server-Sent Events.
- **Model-written prose:** uses `[[L7]]` and `[[L7:"words"]]` line markers, which the backend validates and the frontend renders as time links.

**Tech Stack:** FastAPI, SQLite (stdlib `sqlite3`), Pydantic v2, httpx, Ollama `/api/chat`, whisper.cpp, React + TypeScript + Vite, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-16-feedback-and-learning-redesign-design.md`

## Global Constraints

- **Local only.** All inference goes to the configured loopback Ollama and Whisper. No hosted model calls and no new outbound network calls.
- **Git.** The repository owner makes every commit and push. Executors never run `git commit`, `git push` or `git init`. Each task ends with a suggested commit for the owner.
- **Public repo.** No hostnames, IPs, usernames, absolute home paths or tailnet names in source or docs. Personal reference reviews live only in the gitignored `.local/reference-reviews/`.
- **Recording safety.** Recording, transcription and measurements must work when no model is available, and a failed model step never deletes or overwrites a recording or an earlier pass result.
- **Provenance.** Every saved pass result stores the model that produced it.
- **Per-pass defaults.** Pass names are exactly `technical`, `communication`, `writer`, `chat`, `memory`. Each defaults to the current model and `num_ctx` 8192. `num_predict` defaults to 2048, except `writer`, which defaults to 4096.
- **No model-written quotes or timestamps.**
  - The learner's words and line times appear only through markers that the backend resolves from stored transcript lines.
  - A marker with an unknown line ID is dropped.
  - A quote that isn't an exact substring of its line falls back to the whole line.
- **Scores.**
  - Out of 10 in 0.5 steps, each with a one-line reason, labelled "Coaching estimates, not measurements."
  - The core score names are exactly: `Overall`, `Clarity`, `Structure`, `Conciseness`, `Technical accuracy`, `Technical coverage`, `Handling uncertainty`. Focus-area scores may be added.
- **Coach notes.** Capped at 400 words. Every version is kept. The memory pass never removes a focus area on its own.
- **Day-2 screen.** Before attempt 2 the learner sees only the topic, the prompt and the attempt 2 checklist.
- **Visual tokens.** Use the existing neutral-gray tokens in `frontend/src/styles.css`.
- **Commands from repo root:**
  - `.venv/bin/python -m pytest backend/tests -q`
  - `.venv/bin/ruff check backend`
  - `npm --prefix frontend run build`
  - `npm --prefix frontend test` (Playwright, ports 8766/5174, `data/e2e`)

## Review Focus

1. **Model goes down mid-pipeline**, e.g. the technical pass succeeds and the communication pass fails. Expected: the transcript, measurements and technical result stay visible, the failed pass shows an error with Retry, and retry re-runs only the failed and later passes. Test: `test_pipeline_keeps_earlier_passes_when_later_pass_fails` (Task 7).
2. **A microphone test or near-empty recording** (under 15 words or no topic content). Expected: no invented scores; the review says there was no substantive explanation and suggests re-recording. Test: `test_too_short_attempt_gets_no_scores` (Task 7).
3. **A manually edited transcript** (segments reset to `[]`). Expected: lines are built from sentences without times, no pause marks appear, markers still resolve, and time links show "line 3" instead of a time. Test: `test_edited_transcript_builds_untimed_lines` (Task 2) and the e2e assertion in Task 13.
4. **The learner never answers the note box.** Expected: the review still appears after 5 minutes, and reopening the page later shows it. Test: `test_writer_phase_starts_after_note_timeout` (Task 7).
5. **Trying attempt 2 on the same calendar day, or chatting while analysis runs.** Expected: a clear 409 message ("Attempt 2 opens tomorrow…", "The coach is still reviewing…"), never a crash. Tests: `test_attempt2_same_day_is_refused` (Task 9) and `test_chat_refused_while_analysis_running` (Task 8).

---

## File structure

**Backend (`backend/app/`)**

| File | Status | Responsibility |
|---|---|---|
| `llm.py` | create | Per-pass model and limit lookup; JSON, text and streaming calls to Ollama. `models.structured` delegates here. |
| `transcript.py` | create | Transcript lines with IDs, inline CapCut tokens, the stats line |
| `voice.py` | create | Short plain-sentence voice summary for the model |
| `markers.py` | create | Parse, validate and resolve `[[L…]]` markers |
| `coach.py` | create | Technical, communication, review-structure and review-message passes; correction second check |
| `memory.py` | create | Coach-notes versions and the memory pass |
| `chat.py` | create | Chat context builder, running summary, streaming reply |
| `pipeline.py` | modify | Two-phase orchestration and pass statuses |
| `db.py` | modify | Schema v4 migration |
| `schemas.py` | modify | New request and model-output schemas; drop `Completion` and `TutorInput` |
| `main.py` | modify | New endpoints; retire lesson, tutor, comparison, complete and reanalyze |
| `progress.py` | modify | `derived_recall()`; `compare` removed |
| `models.py` | modify | `structured` moves to `llm.py`; `assess`, `review_insights` and `tutor` are removed after Task 7 |
| `curriculum.py` | modify | `lesson()` removed |

**Frontend (`frontend/src/`)**

| File | Status | Responsibility |
|---|---|---|
| `ReviewPage.tsx` | create | Two-column layout, phone toggle, note box |
| `TranscriptTab.tsx` | create | Inline tokens, stats line, line highlight |
| `ReviewTab.tsx` | create | Scores, key points, checklist, attempt-2 comparison, legacy summary |
| `CoachChat.tsx` | create | Messages, streaming, marker rendering |
| `markers.ts` | create | Turns resolved marker parts into React nodes |
| `CoachNotes.tsx` | create | "What your coach remembers" view, edit and restore |
| `App.tsx` | modify | Stage routing; Settings gains per-pass models and coach notes |
| `Today.tsx` | modify | Pending attempt 2s |
| `ModelPicker.tsx` | modify | Per-pass model selects |
| `types.ts` | modify | New types; `Stage` changes |
| `Learning.tsx` | delete | Retired |
| `Practice.tsx` | modify | Remove `Feedback`, `ComparisonView` and `Transcript`; keep `AttemptStatus` and `AcousticPanel` (used by the Measurements tab) |

**Tests:** `backend/tests/test_llm.py`, `test_transcript.py`, `test_voice.py`, `test_markers.py`, `test_coach.py`, `test_memory.py`, `test_chat.py`, `test_flow.py`, `test_migration.py`, plus updates to `conftest.py`, `test_api.py` and `test_improvements.py`. Frontend: `frontend/e2e/review.spec.ts` (new), plus updates to `practice.spec.ts` and `vocal-variation.spec.ts`; delete `learning.spec.ts`.

---

### Task 0: Capture the baseline (owner-assisted, before Task 7 lands)

The headline result this work is judged by is how local reviews compare with the reference reviews in blind side-by-side judgements. That comparison is the next project, the scoreboard. It needs the old pipeline's output on the same attempts as its baseline.

- [ ] **Step 1: Run the old pipeline.** When the host is running, use `scripts/smoke-inference.py` at commit `c9ffded` (the pre-redesign pipeline) on the recordings or transcripts behind `.local/reference-reviews/`.
  - If recordings aren't available, use `.local/debug_assessment.py`-style transcript-only calls of the old `models.assess` and `models.review_insights`.
- [ ] **Step 2: Save the results.** Save each report under `.local/baseline/2026-11-old-pipeline/`, with the model name, date and settings. The old code also stays in git history, so this can run later. Do it before the old pipeline is forgotten, not after.

---

### Task 1: `llm.py` per-pass call boundary and per-pass settings

**Files:**
- Create: `backend/app/llm.py`
- Modify: `backend/app/models.py:167-232` (`structured` becomes a thin wrapper over `llm.structured_call("technical", …)` so legacy callers keep working until Task 7); `backend/app/main.py:108-139` (settings endpoints)
- Modify: `backend/app/schemas.py` (add `PassSettings`)
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Produces:
  - `PASSES: tuple[str, ...] = ("technical", "communication", "writer", "chat", "memory")`
  - `pass_settings() -> dict[str, dict]` returns `{pass: {"model": str, "num_ctx": int, "num_predict": int}}`. Values come from `app_settings` keys `pass.<name>.model`, `pass.<name>.num_ctx` and `pass.<name>.num_predict`, falling back to `app_settings.ollama_model` (or `settings.ollama_model`), `settings.ollama_context` and `settings.ollama_max_output`.
  - `save_pass_settings(values: dict[str, dict]) -> dict` validates against `PASSES`, against installed models (`models.validate_model_selection`), and against `num_ctx` 4096–32768 and `num_predict` 512–4096.
  - `structured_call(pass_name: str, system: str, payload: dict, schema: type[BaseModel], validate=None, output_schema: dict | None = None) -> tuple[BaseModel, str]` returns `(result, model_used)`. It keeps the existing two-attempt repair loop, `think: False`, temperature 0.15 and the prompt-injection sentence.
  - `text_call(pass_name: str, messages: list[dict]) -> tuple[str, str]` makes a non-streaming chat call and returns `(text, model_used)`.
  - `stream_call(pass_name: str, messages: list[dict]) -> Iterator[str]` yields content chunks from Ollama `stream: True`.
  - All three raise `models.ServiceUnavailable` on HTTP or parse failure.
  - `prompt_budget(pass_name: str) -> int` returns `num_ctx − num_predict`. It is needed because Ollama silently drops the front of a prompt longer than `num_ctx`.
    - Every call estimates prompt tokens as `len(json.dumps(messages)) // 4`.
    - If the estimate exceeds the budget, the call raises `PromptTooLong(ServiceUnavailable)` instead of sending. Callers trim first; see Task 6.
  - `LengthLimited(ServiceUnavailable)` is raised by `structured_call` when Ollama reports `done_reason == "length"`. `text_call` returns the text but sets the attribute `last_truncated = True` so the caller can record a warning.
- Defaults: the `writer` pass defaults to `num_predict` 4096, since a full review runs to about 3,000 tokens. Every other pass defaults to 2048. All passes default to `num_ctx` 8192.
- Endpoints:
  - `GET /api/settings/passes` returns `pass_settings()`.
  - `PUT /api/settings/passes` takes body `PassSettings = {passes: dict[str, {model: str, num_ctx: int, num_predict: int}]}`.
  - The PUT returns 409 while analysis or chat is active, reusing the existing busy check from `PUT /api/settings/model`.

- [ ] **Step 1: Write failing tests** in `test_llm.py`:
  - `test_pass_settings_default_to_current_model_and_limits`: a fresh DB gives `technical.model == settings.ollama_model`, `num_ctx == 8192` and `num_predict == 2048` for every name in `PASSES`.
  - `test_save_pass_settings_rejects_unknown_pass_and_uninstalled_model`: `{"vision": …}` gives `ValueError`, and a model not in `models.installed_models()` (monkeypatched) gives `ValueError`.
  - `test_structured_call_uses_pass_model`: use an httpx `MockTransport` and assert the request JSON `model` equals the saved `pass.communication.model` and `options.num_ctx` equals the saved value. It returns `(parsed, "that-model")`.
  - `test_stream_call_yields_chunks`: the mock returns three NDJSON lines `{"message":{"content":"a"}}…{"done":true}` and the result is `["a","b"]`.
  - `test_prompt_over_budget_raises_without_sending`: the mock transport records zero requests.
  - `test_length_stop_raises_for_structured_and_flags_for_text`: the mock returns `done_reason: "length"`.
  - `test_writer_defaults_to_4096_output`
  - `test_put_settings_passes_busy_returns_409` (API).
- [ ] **Step 2: Run tests and confirm they fail.** Command: `.venv/bin/python -m pytest backend/tests/test_llm.py -q`. Expected: import errors.
- [ ] **Step 3: Implement `llm.py`** and the two endpoints. Make `models.client()` injectable through a module-level `transport` that tests can set.
- [ ] **Step 4: Run tests and confirm they pass.** Run the full backend suite and check the existing tests still pass.
- [ ] **Step 5: Suggest a commit to the owner** (don't run it): `feat: per-pass model settings and llm call boundary`.

---

### Task 2: Transcript lines, CapCut tokens and stats

**Files:**
- Create: `backend/app/transcript.py`
- Test: `backend/tests/test_transcript.py`

**Interfaces:**
- Produces:
  - `build_lines(transcript: str, segments: list[dict]) -> list[dict]` returns `[{"id": "L1", "start": float | None, "end": float | None, "text": str}]`.
    - With segments: one line per segment whose text appears in order in the transcript (reuse `speech.timed_segments`).
    - Without segments: split the transcript into sentences on `(?<=[.!?])\s+`, with `start` and `end` set to `None`.
    - IDs are `L1…Ln`, in order and stable for the same input.
  - `inline_tokens(lines: list[dict], segments: list[dict], filler_events: list[dict], audio_pauses: list[dict]) -> list[dict]` returns tokens of four kinds:
    - `{"type": "word", "text", "line_id", "start"}`
    - `{"type": "filler", "text", "line_id", "start"}`: definite hesitations from `speech_observations` events of kind `hesitation`
    - `{"type": "possible_filler", "text", "line_id", "start"}`: the phrases `you know` and `i mean` from `context-dependent` events. AGENTS.md says context-dependent words are not definite hesitations, so these get a lighter style and a separate count.
    - `{"type": "pause", "seconds": float, "line_id"}`
  - Pause lengths come from the audio measurement `acoustics["pauses"]` (`[{start, duration}]`, from `audio.acoustic_features`), following the 2026-10-27 decision that pauses are measured from audio, not from transcription. Only pauses of at least `PAUSE_MIN_SECONDS = 0.5` are shown, rounded to 0.1.
  - Placement:
    - Before the first word whose `start` ≥ the pause end − 0.15s, using `segments[*].words`.
    - With segments but no word timings, at the start of the first line whose `start` ≥ the pause end − 0.15s.
    - Without any timing (an edited transcript), no pause tokens.
  - Word timing is unverified: real saved attempts on the development machine have no segments to check. The executor confirms with the smoke harness in Task 14; the line-start placement fallback covers the case where whisper.cpp returns no words.
  - `stats(tokens: list[dict], duration: float) -> dict` returns `{"duration": float, "fillers": int, "possible_fillers": int, "pauses_over_1s": int, "longest_pause": float | None}`.

- [ ] **Step 1: Write failing tests.**
  - `test_lines_follow_segments`: two segments give `["L1","L2"]` with their start times.
  - `test_edited_transcript_builds_untimed_lines`: `segments=[]` and the transcript `"One. Two? Three!"` give 3 lines, all with `start is None`.
  - `test_audio_pause_placed_before_next_word`: an audio pause `{start: 1.0, duration: 0.8}` with the next word starting at 1.8 gives a pause token with `seconds == 0.8` immediately before that word. A 0.3s pause gives no token.
  - `test_audio_pause_falls_back_to_line_start_without_word_timings`
  - `test_fillers_inline_and_counted`: a transcript containing "so, the, uh, you know, if" gives a filler token "uh" and a possible_filler token "you know", with `stats()["fillers"] == 1` and `stats()["possible_fillers"] == 1`.
  - `test_stats_longest_pause`.
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement** using word timings from `segments[*].words`, which `models.transcribe` already returns.
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: transcript lines and inline filler/pause tokens`.

---

### Task 3: Voice summary for the model

**Files:**
- Create: `backend/app/voice.py`
- Test: `backend/tests/test_voice.py`

**Interfaces:**
- Consumes: `transcript.build_lines`, `transcript.inline_tokens`, and the `metrics` dict produced in `pipeline.process` (keys `wpm`, `delivery_windows`, `pitch_range_semitones`, `loudness_*`).
- Produces: `voice_summary(metrics: dict, lines: list[dict], tokens: list[dict]) -> list[str]`. At most 6 sentences, each naming line IDs, never containing dense arrays.
  1. The longest pause, with the line it precedes ("Longest pause 1.6s before L7.").
  2. Any pause of at least 3s ("A 13.0s pause before L9.").
  3. The overall pace in words per minute.
  4. The fastest and slowest 30-second window, if they differ by at least 25%, with the lines they cover.
  5. One sentence each on pitch range and loudness range: the values only, with no judgement words like "monotone" or "quiet". This follows AGENTS.md.

- [ ] **Step 1: Write failing tests.**
  - `test_summary_names_longest_pause_line`
  - `test_summary_has_no_judgement_words`: assert none of `monotone`, `quiet`, `boring`, `confident`, `nervous` appear.
  - `test_summary_at_most_six_sentences_and_no_arrays`: assert no `[` characters.
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: compact voice summary for coach prompts`.

---

### Task 4: Line markers

**Files:**
- Create: `backend/app/markers.py`
- Test: `backend/tests/test_markers.py`

**Interfaces:**
- Produces:
  - `MARKER = re.compile(r'\[\[(L\d+)(?::"([^"]+)")?\]\]')`
  - `resolve(text: str, lines: list[dict]) -> list[dict]` returns parts. A part is either `{"type": "text", "text": str}` or `{"type": "ref", "line_id": str, "start": float | None, "quote": str}`.
    - Unknown IDs become nothing.
    - When the quote is an exact case-insensitive substring of the line text (whitespace-normalised), `quote` is the original characters from the line. Otherwise `quote` is the whole line text.
    - A bare `[[L7]]` has `quote = ""`.
  - `strip_unknown(text: str, lines: list[dict]) -> str` removes markers with unknown IDs. It is used before storing model prose.
  - `plain_timestamp_pattern = re.compile(r'\b\d{1,2}:\d{2}\b')`, used by Task 6 to flag model prose that writes raw times.

- [ ] **Step 1: Write failing tests.**
  - `test_resolve_bare_and_quoted_marker`
  - `test_unknown_line_dropped`
  - `test_inexact_quote_falls_back_to_whole_line`
  - `test_quote_whitespace_and_case_tolerant_but_returns_original`
  - `test_text_between_markers_preserved`
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: validated transcript line markers`.

---

### Task 5: Schema v4 migration

**Files:**
- Modify: `backend/app/db.py:30-75`
- Test: `backend/tests/test_migration.py`

**Changes:**
- `attempts` gains these columns:
  - `lines TEXT`
  - `tokens TEXT`
  - `analysis TEXT` (JSON; see the shape below)
  - `learner_note TEXT`
  - `note_state TEXT NOT NULL DEFAULT 'pending'`, one of `pending`, `submitted`, `skipped` or `legacy`
  - `note_deadline TEXT`, an ISO timestamp
  - `chat_summary TEXT`
  - `chat_summary_through INTEGER NOT NULL DEFAULT 0`
- `messages` gains these columns:
  - `attempt_number INTEGER NOT NULL DEFAULT 1`
  - `kind TEXT NOT NULL DEFAULT 'chat'`, one of `chat` or `review`
- `sessions` gains `attempt2_after TEXT`.
- New table: `coach_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('memory','learner','restore')), folded_attempt_ids TEXT NOT NULL DEFAULT '[]')`.
- Stage remap:
  - `feedback` and `learn` become `review1`
  - `compare` becomes `review2`
  - existing rows with `stage='review1'` get `attempt2_after` set to the date of their `created_at`, so old sessions aren't locked out
- Existing attempts that have an `assessment` get `note_state='legacy'`.
- `PRAGMA user_version=4`. The guard becomes `version > 4`.

`analysis` JSON shape (Task 7 fills it):
```json
{"version": 1,
 "voice_summary": ["…"],
 "stats": {"duration": 116.0, "fillers": 2, "pauses_over_1s": 3, "longest_pause": 1.6},
 "passes": {"technical": {"status": "done|failed|waiting|pending", "model": "…", "error": "…"}, "communication": {}, "memory": {}, "writer": {}},
 "technical": {}, "communication": {}, "timing": [], "review": {}}
```

- [ ] **Step 1: Write failing tests.**
  - `test_v3_database_migrates_stages_and_columns`: build a v3 database with the old `executescript`, insert sessions in stages `feedback`, `learn` and `compare`, call `db.initialize()`, then assert the stages are `review1`, `review1` and `review2`, that `user_version == 4`, that the new columns exist, and that the legacy attempt has `note_state == 'legacy'`.
  - `test_newer_database_refused`: version 5 raises `RuntimeError`.
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.** Use idempotent `ALTER TABLE … ADD COLUMN` guarded by `PRAGMA table_info`, as the existing code does.
- [ ] **Step 4: Run tests and confirm they pass**, along with the existing restart-recovery test.
- [ ] **Step 5: Suggest a commit:** `feat: schema v4 for review pipeline, notes and day split`.

---

### Task 6: Coach passes

**Files:**
- Create: `backend/app/coach.py`
- Modify: `backend/app/schemas.py` (model-output schemas below)
- Test: `backend/tests/test_coach.py`

**Interfaces:**
- Consumes:
  - `llm.structured_call` and `llm.text_call`
  - `markers.resolve` and `markers.strip_unknown`
  - the topic dict from `curriculum.CATALOG` (`concepts[*].id/name/reference/bridge`, `practice`, `nuance`)
- Output schemas in `schemas.py`, all `StrictModel`:
  - `TechnicalAnalysis`:
    - `concepts: list[{concept_id: enum(topic ids), status: correct|partial|missing|incorrect, line_ids: list[str], note: str}]`, exactly one per topic concept
    - `corrections: list[{line_id: str, claim: str, correction: str, basis: "reference"|"model", reference_ids: list[str]}]`, at most 4
    - `senior_points: list[{point: str, basis: "reference"|"model"}]`, 3–7 items
  - `CommunicationAnalysis`:
    - `sections: list[{label: str, first_line: str, last_line: str}]`, 1–6 items
    - `points: list[{kind: "strength"|"problem", line_id: str, observation: str, rewrite: str}]`, at most 6
    - `gaps: list[{section_label: str, kind: "knowledge"|"communication"|"unclear", reason: str}]`
    - `focus: list[{area: str, observation: str}]`
  - `ReviewStructure`:
    - `scores: list[{name: str, score: float (0–10, multiple of 0.5), reason: str (≤ 120 chars)}]`, which must include all 7 core names
    - `key_points: list[{text: str, line_ids: list[str]}]`, exactly 3
    - `checklist: list[str]`, 2–5 items
    - `comparison: {changes: list[{name: str, before: float, after: float}], what_changed: str} | None`
- Produces (each returns `(result_dict, model_used)`):
  - `technical_pass(topic: dict, prompt: str, lines: list[dict]) -> tuple[dict, str]`
    - Validation: every `line_ids`/`line_id` must be in `lines`, and `reference_ids` must be in `{concept ids} ∪ {id+"_context"} ∪ {"practice"}`.
    - `basis == "reference"` requires at least one reference ID.
    - After parsing, every correction goes through `verify_corrections`.
  - `verify_corrections(topic: dict, lines: list[dict], corrections: list[dict]) -> list[dict]`
    - A bounded second `structured_call("technical", …)` using the existing second-check instructions from `models.review_insights` (`models.py:519-535`), moved here verbatim and adapted from excerpt IDs to line IDs.
    - A correction that is withdrawn is removed. One that can't be confirmed, or a second call that fails, gets `verified = False`. Otherwise `verified = True`.
  - `communication_pass(lines: list[dict], voice_summary: list[str], coach_notes: str, learner_context: dict) -> tuple[dict, str]`
    - `learner_context = {"prompt": str, "duration": float}`
    - Validation: line IDs exist, and sections are in order and non-overlapping.
  - `section_timing(sections: list[dict], lines: list[dict], duration: float) -> list[dict]` returns `[{label, start, end, seconds, percent}]`. It is pure code and returns `[]` when lines are untimed.
  - `review_structure_pass(technical: dict, communication: dict, timing: list[dict], coach_notes: str, learner_note: str | None, previous_review: dict | None) -> tuple[dict, str]`
    - When `previous_review` is not `None`, `comparison` is required and `changes.before` must equal the previous score for the same name.
  - `review_message_pass(lines: list[dict], technical: dict, communication: dict, timing: list[dict], review: dict, coach_notes: str, learner_note: str | None) -> tuple[str, str]`
    - Uses `text_call("writer", …)`.
    - The system prompt requires markers for every quote or moment, forbids writing times, and asks for the reference structure:
      1. respond to the learner's note
      2. three connected priorities
      3. where the time went
      4. quoted moments with rewrites
      5. technical corrections and what to learn
      6. an example strong answer
      7. one focus for next time
    - Afterwards, the code runs `markers.strip_unknown`. If `plain_timestamp_pattern` matches, it makes one repair request asking for markers instead. If the pattern still matches, the times are left in place but `analysis.passes.writer.warning` is set.
  - `too_short(lines: list[dict]) -> bool` is true when there are fewer than 15 words in total.
  - `fit_payload(pass_name: str, payload: dict, trim_order: list[str]) -> dict` drops or shortens payload keys in `trim_order` until the estimate fits `llm.prompt_budget(pass_name)`. Transcript lines are never trimmed. Trim orders:
    - technical: topic `nuance`, then `practice`, then each concept's `bridge`
    - communication: `voice_summary` (keep the first 2 sentences), then `coach_notes` (keep the focus section)
    - writer: `communication.points[*].observation` text over 200 characters, then `technical.senior_points`
    - If the payload still doesn't fit, the call raises `PromptTooLong`.

- [ ] **Step 1: Write failing tests**, using a `fake_llm` fixture (added to `conftest.py` in this task) that maps a pass name to a queue of JSON or text responses and records the requests:
  - `test_technical_pass_rejects_unknown_line_ids_then_repairs`
  - `test_technical_pass_has_one_result_per_concept`
  - `test_reference_basis_requires_reference_id`
  - `test_verify_corrections_marks_unverified_when_second_call_fails`
  - `test_verify_corrections_removes_withdrawn`
  - `test_section_timing_percentages_sum_to_100_when_timed`
  - `test_section_timing_empty_when_untimed`
  - `test_review_structure_requires_all_core_scores`
  - `test_scores_must_be_half_steps_in_range`
  - `test_attempt2_review_requires_comparison_matching_previous_scores`
  - `test_review_message_unknown_markers_stripped`
  - `test_review_message_raw_timestamp_triggers_one_repair`
  - `test_communication_prompt_contains_coach_notes_and_voice_summary`: inspect the recorded request payload.
  - `test_fit_payload_trims_in_order_and_never_drops_lines`
  - `test_review_message_truncation_recorded_as_warning`
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.** Keep each system prompt in a module-level constant: `TECHNICAL_SYSTEM`, `COMMUNICATION_SYSTEM`, `STRUCTURE_SYSTEM`, `MESSAGE_SYSTEM`. Each one states its single job.
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: technical, communication and writer coach passes`.

---

### Task 7: Memory and two-phase pipeline

**Files:**
- Create: `backend/app/memory.py`
- Modify: `backend/app/pipeline.py` (rewrite `process`), `backend/app/main.py` (attempt upload, retry, transcript edit and new note endpoint), `backend/app/models.py` (delete `assess`, `review_insights`, `validate_assessment`, `transcript_excerpts`, `resolve_assessment_evidence` and the `measurement_summary` callers; keep `transcribe`, `health`, `installed_models`, `validate_model_selection`, `ServiceUnavailable`, `client`)
- Modify: `backend/tests/conftest.py` (replace the `assess`/`review_insights`/`tutor` doubles with `fake_llm` defaults that return valid minimal outputs for every pass)
- Test: `backend/tests/test_memory.py`, `backend/tests/test_flow.py` (pipeline parts)

**Interfaces:**
- `memory.py` produces:
  - `current_notes() -> dict` returns `{"id": int | None, "content": str}`, with an empty string when none exist.
  - `versions() -> list[dict]`, newest first.
  - `save_learner_edit(content: str) -> dict`: source `learner`, `ValueError` over 400 words.
  - `restore(version_id: int) -> dict`: source `restore`.
  - `unfolded_attempts() -> list[dict]`: attempts whose id isn't in any `folded_attempt_ids` and that have a review message. Each item contains the transcript lines, review, learner note and chat messages for that attempt.
  - `fold_in() -> dict | None` runs the memory pass when there are unfolded attempts.
    - Input: current notes plus a compact digest of each unfolded attempt (review key points, scores, learner note, and the learner's own chat messages only).
    - Output: new content (≤ 400 words; one repair if longer). It is saved with source `memory` and `folded_attempt_ids`.
    - If a focus-area heading present in the old notes is missing from the new ones, one repair is requested. If it is still missing, the old focus section is appended unchanged.
    - On failure it returns `None` and leaves the notes untouched.
- `pipeline.py` produces:
  - `submit(attempt_id)` keeps its existing signature.
  - `process(attempt_id)` is phase 1:
    1. acoustics and transcription, as today
    2. `lines`, `tokens`, `stats` and `voice_summary`, stored
    3. if `coach.too_short`, set `analysis.review = {"too_short": True}` and stop
    4. `memory.fold_in()`, whose failure is recorded but doesn't block. It runs first so the communication pass judges focus areas with everything said in earlier sessions.
    5. the `technical` pass, then the `communication` pass, each saved immediately with status, model and error
    6. if `note_state != 'pending'`, call `submit_writer`. Otherwise store `note_deadline = now + NOTE_TIMEOUT_SECONDS (300)` and start a `threading.Timer` that calls `auto_skip` as the fast path.
  - `auto_skip(attempt_id)` sets `note_state='skipped'` only if it is still `pending`, then calls `submit_writer`.
  - `sweep_note_deadlines() -> None` auto-skips every pending attempt whose `note_deadline` has passed and whose phase 1 is done. It runs from `db.initialize()` at startup and on every `GET /api/sessions/{id}`, so a restart during the wait can't leave a review stuck. The host lost power once already.
  - `submit_writer(attempt_id)` and `write(attempt_id)` are phase 2:
    1. the `review_structure_pass`, which receives the attempt 1 review when this is attempt 2
    2. the `review_message_pass`, which inserts a `messages` row with `kind='review'` and `attempt_number`
    3. for attempt 2, auto-complete the session (Task 9)
  - The memory pass runs in phase 1, not here.
  - A pass whose prerequisite failed is set to `pending`.
  - `retry(attempt_id)` re-runs from the first pass that isn't `done`.
- Endpoint: `POST /api/attempts/{id}/note` with body `LearnerNote = {text: str | None (≤ 2000 chars), skip: bool}`. It is accepted only when `note_state == 'pending'`, sets `submitted` or `skipped`, and calls `submit_writer` if phase 1 is done. Otherwise phase 1 picks it up.
- `GET /api/sessions/{id}` attempts now include `lines`, `tokens`, `analysis` (the parsed JSON), `learner_note` and `note_state`. Messages include `attempt_number` and `kind`, and each message has `parts` from `markers.resolve` against that attempt's lines.

- [ ] **Step 1: Write failing tests.**
  - `test_memory_versions_and_restore`
  - `test_learner_edit_over_400_words_rejected`
  - `test_fold_in_keeps_focus_area_the_model_dropped`
  - `test_fold_in_failure_leaves_notes_unchanged`
  - `test_pipeline_runs_phase1_then_waits_for_note`
  - `test_note_submit_runs_writer_and_creates_review_message`
  - `test_writer_phase_starts_after_note_timeout`: monkeypatch `NOTE_TIMEOUT_SECONDS = 0` and `threading.Timer` to call immediately.
  - `test_pipeline_keeps_earlier_passes_when_later_pass_fails`: the communication pass raises `ServiceUnavailable`. Assert the technical pass is `done`, communication is `failed`, the writer passes are `pending`, the transcript is present, and retry then completes everything.
  - `test_too_short_attempt_gets_no_scores`
  - `test_review_receives_folded_notes`: assert that both the communication and structure request payloads contain the notes text the memory pass produced from the previous attempt's chat.
  - `test_note_deadline_survives_restart`: set the phase 1 status to done, with `note_state='pending'` and `note_deadline` in the past. Call `db.initialize()` and then `sweep_note_deadlines()`, and assert the review message exists.
  - `test_offline_models_still_allow_recording_and_transcript`: replaces the old `test_offline_models_still_allow_entire_workflow`.
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.** Remove the legacy model functions and update `test_api.py` and `test_improvements.py`. Delete tests that only covered the retired assessment and reanalyze behaviour, and list the deleted test names in the task report. `models.tutor` and the lesson and tutor endpoints stay until Task 8.
- [ ] **Step 4: Run tests and confirm they pass.** Run the full backend suite plus ruff.
- [ ] **Step 5: Suggest a commit:** `feat: two-phase coach pipeline with learner note and coach-notes memory`.

---

### Task 8: Coach chat with streaming and running summary

**Files:**
- Create: `backend/app/chat.py`
- Modify: `backend/app/main.py` (replace `POST /tutor` with `POST /api/sessions/{id}/chat`; delete `GET /lesson` and `curriculum.lesson`), `backend/app/models.py` (delete `tutor`)
- Modify: `backend/app/schemas.py` (`ChatInput = {message: str (1–4000), attempt_number: 1|2}`)
- Test: `backend/tests/test_chat.py`

**Interfaces:**
- Produces:
  - `build_context(session: dict, attempt: dict, history: list[dict], budget_tokens: int) -> list[dict]` returns Ollama messages in this order:
    1. system prompt `CHAT_SYSTEM`
    2. a single system "context" message holding, in order: coach notes, transcript lines (`L1: …`), review structure, technical analysis, communication analysis and the topic reference
    3. `chat_summary`, if any
    4. the turns after `chat_summary_through`
  - Tokens are estimated as `len(text) // 4`.
  - `needs_summary(messages: list[dict], budget_tokens: int) -> bool` is true when the estimate exceeds 75% of the budget.
  - `summarize(attempt_id: int, older: list[dict]) -> None` folds the oldest turns, keeping the latest 4, into `chat_summary` with `text_call("chat", …)` and advances `chat_summary_through`.
  - `stream_reply(session_id: str, attempt_number: int, message: str) -> Iterator[str]` yields SSE lines:
    - `data: {"delta": "…"}` for each chunk
    - then `data: {"done": true, "message": {...stored message with parts...}}`
    - on failure, `data: {"error": "…"}`
  - It stores the user message before streaming and the assistant message after `strip_unknown`.
- Endpoint: `POST /api/sessions/{id}/chat` returns `StreamingResponse(media_type="text/event-stream")`.
  - It returns 409 "The coach is still reviewing this attempt." while the attempt's status is `pending` or `processing`, or a writer pass is `pending` or running.
  - A writer pass that has failed doesn't block chat. The context then uses whatever analyses exist, so one bad writer output can't lock the conversation.
  - `CHAT_SYSTEM` must:
    - teach what the learner asks for, such as the senior-engineer answer, a simpler version, alternatives or text diagrams
    - after explaining a concept, sometimes end with one optional check question, or invite the learner to explain it back in their own words
    - correct inaccurate claims before building on them
    - never hand over a script to memorize for attempt 2
    - use markers for every reference to the learner's words
    This comes from the learner's own description of the tutoring they want (`.local/reference-reviews/2026-11-13-…`).
  - It returns 409 when another chat reply is in progress (the existing `tutor_lock`).
  - It returns 409 for `attempt_number` 2 before attempt 2 exists.

- [ ] **Step 1: Write failing tests.**
  - `test_context_keeps_review_transcript_and_notes_when_summarized`
  - `test_summary_triggers_over_75_percent_budget_and_keeps_last_four_turns`
  - `test_chat_streams_deltas_then_done_with_parts`
  - `test_chat_refused_while_analysis_running`
  - `test_parallel_chat_refused`
  - `test_chat_allowed_when_writer_failed`
  - `test_context_fits_prompt_budget`: the context built for a 60-turn history must come within `llm.prompt_budget("chat")`.
  - `test_chat_reply_unknown_markers_stripped`
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: streaming coach chat with running summary`.

---

### Task 9: Day split, auto-completion and the Today queue

**Files:**
- Modify: `backend/app/main.py` (`stage`, `upload`, `reviews`, `history`, recommendation; delete `complete` and `comparison`)
- Modify: `backend/app/progress.py` (add `derived_recall`; delete `compare`)
- Modify: `backend/app/schemas.py` (`StageChange.stage` becomes `record1|review1|record2|review2`; delete `Completion`)
- Test: `backend/tests/test_flow.py`

**Interfaces:**
- `progress.derived_recall(mastery: float | None) -> str` returns:
  - `"good"` when mastery is ≥ 0.8
  - `"hard"` when it is ≥ 0.5
  - `"again"` when it is lower or `None`
- Uploading attempt 1:
  - sets stage `review1` and `attempt2_after = (local date of upload + 1 day).isoformat()`
- `PUT stage → record2`:
  - returns 409 "Attempt 2 opens tomorrow so it tests what you remember." when `date.today().isoformat() < attempt2_after`
- Uploading attempt 2:
  - sets stage `review2`
- After the attempt 2 writer phase completes, `complete_session(session_id) -> None` runs:
  - `progress.schedule(previous, derived_recall(mastery), mastery)`, where mastery comes from attempt 2's `analysis.technical.concepts` (same formula as `progress.mastery`)
  - then sets `completed_at`, `recall` and `review_due` and upserts `reviews`
  - It is idempotent.
- `GET /api/reviews` changes:
  - it excludes topics that have a session with `stage IN ('review1','record2')` and no `completed_at`
  - it adds `GET /api/attempt2` returning `[{session_id, topic, attempt2_after, available: bool}]`
- Recommendation "weak" topics read attempt 2's `analysis.technical` and fall back to the legacy `assessment`.

- [ ] **Step 1: Write failing tests.**
  - `test_attempt2_same_day_is_refused`
  - `test_attempt2_allowed_next_day`: monkeypatch `main.date` or freeze `date.today`.
  - `test_session_autocompletes_after_attempt2_review_and_schedules`
  - `test_derived_recall_thresholds`
  - `test_today_queue_lists_pending_attempt2_and_hides_its_spaced_review`
  - `test_pending_attempt2_never_expires`: 30 days later it is still listed.
  - `test_legacy_session_weak_topics_use_old_assessment`
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests and confirm they pass.** Run the full suite and ruff.
- [ ] **Step 5: Suggest a commit:** `feat: attempt 2 on a later day with automatic completion`.

---

### Task 10: Coach notes API, re-review of legacy attempts, smoke harness

**Files:**
- Modify: `backend/app/main.py`, `scripts/smoke-inference.py`
- Test: `backend/tests/test_memory.py` (API), `backend/tests/test_flow.py`

**Interfaces:**
- `GET /api/coach-notes` returns `{current, versions}`.
- `PUT /api/coach-notes` takes `{content}` and saves it as a learner edit; it returns 422 over 400 words.
- `POST /api/coach-notes/{version_id}/restore`
- `POST /api/attempts/{id}/rereview`:
  - archives the public attempt snapshot into `analysis_history` (existing pattern)
  - resets `analysis`, sets `note_state='skipped'` and deletes that attempt's `kind='review'` message
  - submits phase 1
  - returns 409 while processing
- `scripts/smoke-inference.py run(cold, learned)` drives the new pipeline end to end against the real models, in a temporary database. Its report adds:
  - per-pass `status`, `model` and `seconds`
  - the review structure
  - the first 1,500 characters of the review message
  - one chat reply to "What would a senior engineer say?"

- [ ] **Step 1: Write failing tests.**
  - `test_coach_notes_api_edit_and_restore`
  - `test_rereview_archives_previous_and_reruns`
  - `test_rereview_refused_while_processing`
- [ ] **Step 2: Run tests and confirm they fail.**
- [ ] **Step 3: Implement**, including the smoke-harness update. The harness is not unit-tested; it needs the real models.
- [ ] **Step 4: Run tests and confirm they pass.**
- [ ] **Step 5: Suggest a commit:** `feat: coach notes API, legacy re-review, updated smoke harness`.

---

### Task 11: Review page, part A: types, API helpers and marker rendering

Tasks 11 and 12 are one reviewable unit, because the frontend doesn't compile between them. Implement both, then review them together. The suggested commit comes at the end of Task 12.

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`
- Create: `frontend/src/markers.ts`

**Interfaces:**
- Types:
  - `Stage = "record1" | "review1" | "record2" | "review2"`
  - `Line {id: string; start: number | null; end: number | null; text: string}`
  - `Token`: a union of `word`, `filler`, `possible_filler` and `pause`, as in Task 2
  - `PassStatus`
  - `Analysis`: as in Task 5
  - `ReviewStructure`, `TechnicalAnalysis`, `CommunicationAnalysis`: as in Task 6
  - `MessagePart = {type: "text"; text: string} | {type: "ref"; line_id: string; start: number | null; quote: string}`
  - `Message` gains `attempt_number`, `kind` and `parts`
  - `Attempt` gains `lines`, `tokens`, `analysis`, `learner_note` and `note_state`
  - `PassSettings`, `CoachNotes`, `Attempt2Item`
- `api.ts`:
  - `streamChat(sessionId: string, attempt: 1 | 2, message: string, onDelta: (t: string) => void): Promise<Message>` uses `fetch` with a `ReadableStream` reader that parses `data:` lines. It sends the existing `X-SpeakLab-Client` header and rejects with the server's error text.
- `markers.ts`:
  - `renderParts(parts: MessagePart[], onRef: (lineId: string) => void): ReactNode[]` renders a ref as `<button class="time-ref">` labelled `timeLabel(start)`, or `line N` when `start` is `null`, followed by the quote in quotation marks when it isn't empty.
  - `stripMarkersForStreaming(text: string): string` renders `[[L7…]]` as `…` while a message is still streaming.

- [ ] **Step 1: Implement**, since types are covered by `tsc`.
- [ ] **Step 2: Continue directly to Task 12.** The build is verified there.

---

### Task 12: Review page, part B: transcript, review and measurements tabs, chat, note box

**Files:**
- Create: `frontend/src/ReviewPage.tsx`, `TranscriptTab.tsx`, `ReviewTab.tsx`, `CoachChat.tsx`
- Modify: `frontend/src/App.tsx:420-475` (stage routing), `frontend/src/Practice.tsx` (remove `Feedback`, `ComparisonView` and `Transcript`), `frontend/src/styles.css`
- Delete: `frontend/src/Learning.tsx`, `frontend/e2e/learning.spec.ts`
- Test: `frontend/e2e/review.spec.ts` (Playwright with `page.route` API mocks, following `practice.spec.ts`)

**Interfaces:**
- `ReviewPage({session, attemptNumber, onSession}: {session: Session; attemptNumber: 1 | 2; onSession: (s: Session) => void})`
  - **Desktop (≥ 900px):** two columns. The left has tabs `Transcript | Review | Measurements`, defaulting to Review once the review exists and to Transcript before that. The right holds `CoachChat`.
  - **Under 900px:** the chat fills the screen, and a "Transcript & review" button opens the tabs in a full-screen sheet.
  - While `note_state === "pending"`, a note box sits above the chat with the heading "How did that go?", a textarea, and Send and Skip buttons. These post to `/api/attempts/{id}/note`.
  - Pass progress shows as one line, e.g. "Reading the technical side… the communication side… writing". Each failed pass shows its error with a Retry button (`POST /api/attempts/{id}/retry`).
- `TranscriptTab({attempt, highlighted}: {attempt: Attempt; highlighted: string | null})`
  - The stats line reads: `1:56 · 1 filler, 1 possible · 3 pauses over 1s · longest 1.6s`.
  - Each line shows its `timeLabel(start)` only when `start` isn't `null`.
  - Fillers render as `<mark class="filler">`, possible fillers as `<mark class="filler possible">` (lighter), and pauses as `<span class="pause">0.8s</span>`.
  - The line matching `highlighted` gets the class `highlight` and is scrolled into view.
- `ReviewTab({attempt, previous}: {attempt: Attempt; previous?: Attempt})`
  - Scores render as chips `Name 6.5` with the reason in the `title` attribute and as text on tap. The 7 core scores come first.
  - Below the scores: the caption "Coaching estimates, not measurements.", then the key points with `time-ref` buttons, then "For attempt 2" with the checklist.
  - For attempt 2: the score changes (e.g. `Structure 6.0 → 8.0`) and `what_changed`.
  - For a `note_state === "legacy"` attempt: the old assessment summary and concept statuses, plus a "Re-review with the new coach" button.
  - When `analysis.review.too_short` is set: "No substantive explanation was recorded. Record again when you're ready."
- Measurements tab: the existing `AcousticPanel` and `VocalVariation` inside a collapsed `<details>`, with the summary "Voice measurements (pace, pitch, volume, pauses)".
- `CoachChat({session, attemptNumber, onRef})`
  - Shows messages for `attemptNumber`, with the `kind === "review"` message first.
  - Renders `parts` through `renderParts`, streams through `streamChat`, and disables the composer while a reply streams or the coach is reviewing.
  - The composer placeholder is "Ask about your attempt or the topic…".
- Routing in `App.tsx`:
  - `record1` shows `Recorder`
  - `review1` shows `ReviewPage(1)` plus a "Done for today" button that returns to Today
  - `record2` shows the day-2 screen (topic title, prompt and the attempt 1 `review.checklist` only), then `Recorder`
  - `review2` shows `ReviewPage(2)`
  - Topic references stay hidden on both recording screens (an existing rule).

- [ ] **Step 1: Write failing Playwright tests** in `review.spec.ts`:
  - `review page shows inline fillers and pauses and highlights a line from a chat time link`: click the `1:24` ref and expect the line to have the class `highlight`.
  - `note box send and skip`: expect the POST body and the box to disappear.
  - `failed pass shows retry and keeps transcript`: covers Review Focus 1.
  - `edited transcript shows line labels instead of times`: covers Review Focus 3.
  - `too-short attempt shows no scores`
  - `scores, key points and checklist stay in review tab while chat grows`: add 10 messages and expect the Review tab content to be unchanged.
  - `phone width shows chat with transcript and review sheet`
  - `day 2 screen shows only topic, prompt and checklist`: expect the text of the review key points to be absent.
  - `legacy attempt shows old summary and re-review button`
- [ ] **Step 2: Run the tests and confirm they fail.** Command: `npm --prefix frontend test -- review.spec.ts`
- [ ] **Step 3: Implement.** Update `practice.spec.ts` for the new stages, and `vocal-variation.spec.ts` to open the Measurements tab first.
- [ ] **Step 4: Run and confirm everything passes.** Run `npm --prefix frontend run build` and `npm --prefix frontend test`.
- [ ] **Step 5: Suggest a commit:** `feat: review page with transcript, review, measurements and coach chat`.

---

### Task 13: Today queue, Settings (per-pass models, coach notes)

**Files:**
- Modify: `frontend/src/Today.tsx`, `frontend/src/ModelPicker.tsx`, `frontend/src/App.tsx` (Settings section)
- Create: `frontend/src/CoachNotes.tsx`
- Test: `frontend/e2e/review.spec.ts` (append), `frontend/e2e/practice.spec.ts`

**Interfaces:**
- Today shows a "Second attempts" list from `GET /api/attempt2`.
  - Available items get a "Record attempt 2" button (`PUT stage record2`).
  - Unavailable items show "Opens tomorrow".
- `ModelPicker` gets an "Advanced: model per step" `<details>` with one select per pass, labelled:
  - Technical review
  - Communication review
  - Review writer
  - Chat
  - Coach notes
  Options come from `/api/models`, and the selects save through `PUT /api/settings/passes`, with the existing busy and unavailable handling. The existing single picker sets all five at once.
- `CoachNotes` sits in Settings under the heading "What your coach remembers".
  - It shows the current notes as text, with an "Edit" button that opens a textarea, a word count (red over 400), and Save and Cancel buttons.
  - A "Previous versions" `<details>` lists each version's date and source, with a "Restore" button on each.

- [ ] **Step 1: Write failing Playwright tests.**
  - `today lists second attempts and opens tomorrow label`
  - `per-pass model selects save`
  - `coach notes edit, over-limit warning, restore`
- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run and confirm everything passes.** Run the build plus the full Playwright suite, then the full backend suite and ruff.
- [ ] **Step 5: Suggest a commit:** `feat: second-attempt queue, per-step models and coach notes settings`.

---

### Task 14: Docs and real-model check (owner-assisted)

**Files:**
- Modify: `AGENTS.md`:
  - replace the "Feedback and reanalysis" and "Interface" sections with the new pipeline
  - replace the "one model / 8192 / 2048" line with the per-pass defaults
- Modify: `README.md` (the workflow description)

- [ ] **Step 1: Update the docs.** No machine-specific values.
- [ ] **Step 2: Real-model check.** This needs the host PC, which the owner must have running.
  - Deploy following `docs/deployment.md`.
  - Run `scripts/smoke-inference.py` on two saved recordings.
  - Record per-pass seconds and VRAM.
  - Report any review over 3 minutes, or any out-of-memory error, to the owner. Don't silently drop passes.
- [ ] **Step 3: Prompt tuning.** Compare smoke-harness reviews with `.local/reference-reviews/*.md`.
  - Adjust the four system prompts until the reviews follow the reference shape (connected priorities, timing, quoted rewrites, technical corrections, an example answer, one focus).
  - Keep the tuning notes in `.local/`, not in the repo.
- [ ] **Step 4: Owner review.** The owner records real attempts and judges the review and chat. This is the spec's definition of done.
- [ ] **Step 5: Suggest a commit:** `docs: describe coach pipeline and review page`.
