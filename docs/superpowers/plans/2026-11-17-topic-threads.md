# Topic Threads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace "session with attempts 1–2 and a stage machine" with one ongoing thread per topic: unlimited attempts on later days, a topic page that keeps every attempt's review and chat reachable, lazily created threads, and a Today page that never offers a practised topic as new.

**Architecture:** The `sessions` row becomes the topic thread. Its stage and completion columns are no longer used. A new `backend/app/threads.py` derives all thread state from the attempts: next attempt date, whether recording is allowed, which attempt can be replaced, and the latest checklist. Topic-keyed endpoints replace the stage endpoints. The frontend routes to `#/topic/<id>` instead of walking stages.

**Spec:** `docs/superpowers/specs/2026-11-17-topic-threads-design.md`. Read it first.

## Global Constraints

- Every constraint in `docs/superpowers/plans/2026-11-16-feedback-and-learning-redesign.md` "Global Constraints" still holds: local-only inference, recording safety, provenance, markers, scores, coach-notes cap, neutral tokens, public-repo rule.
- **No git commands that change state.** No commit, add, stash, branch, checkout or push. Leave everything uncommitted in the working tree.
- **Dates** are the server's local `date.today()`.
- **Database:** `user_version` becomes 5, and `initialize()` refuses anything above 5. The migration must also be correct for the host's real database. That database was originally marked v4 by an earlier branch and has since been upgraded to v4 by the redesign. It has `learning_sessions` and `learning_turns` tables, which must be left alone.
- **Exact copy:**
  - "Ready for another attempt"
  - "Suggested topics"
  - "Include practised"
  - "Pick up where you left off"
  - "New attempt"
  - "Next attempt opens tomorrow"
  - "Try a different angle"
  - "For next time"

## Review Focus

1. **Real host data upgraded twice.** Expected: every recorded session reachable from its topic page, attempts in date order, no empty sessions listed. Test: a migration test that builds a v4 database matching the host's shape.
2. **A topic picked but never recorded.** Expected: no thread row, nothing in History. Test: `test_picking_a_topic_creates_nothing`.
3. **A new attempt requested the same day.** Expected: 409 "Next attempt opens tomorrow". The one exception is replacing a too-short latest attempt.
4. **Chat or note for attempt 3 and above.** Expected: everything that worked for attempts 1–2 works for N. The old `Literal[1,2]` schema and the CHECK constraint are both removed.
5. **Old `#/session/<id>` bookmarks.** Expected: redirect to the topic page.

---

### Task 1: Schema v5 migration

**Files:** Modify `backend/app/db.py`. Test `backend/tests/test_migration.py`.

- [ ] Write the failing tests first:
  - `test_v4_database_upgrades_to_v5_and_drops_attempt_number_check`: after `initialize()`, inserting attempt number 3 succeeds and `user_version == 5`.
  - `test_recorded_sessions_of_one_topic_merge_into_earliest_thread`: two recorded sessions on one topic become one thread. Attempts are renumbered 1..n by `created_at`. Their `messages.attempt_number`, `analysis_history` and the merged session's messages move with them. Empty sessions are untouched.
  - `test_host_shaped_v4_database_upgrades`: a v4 database with the redesign columns plus `learning_sessions` and `learning_turns` rows keeps every attempt, and the learning tables are unchanged.
  - `test_v5_initialize_is_idempotent`.
  - `test_newer_than_v5_refused`.
- [ ] Implement:
  - Rebuild `attempts` without the CHECK constraint, inside one transaction with `PRAGMA foreign_keys=OFF` around the rebuild. Copy every column, then recreate the index.
  - Keep `UNIQUE(session_id, number)`.
  - The merge step runs only when upgrading from below 5.
- [ ] Run the full backend suite and ruff.

### Task 2: Thread backend

**Files:**
- Create `backend/app/threads.py`.
- Modify `backend/app/main.py`, `pipeline.py`, `schemas.py`, `progress.py`, `chat.py` (if needed) and `scripts/smoke-inference.py`.
- Tests: `backend/tests/test_threads.py` (new), plus updates to test_api, test_flow and test_chat.

**Interfaces produced:**

`threads.py`:
- `thread_for_topic(topic_id) -> dict | None`: the earliest session for the topic that has at least one attempt.
- `attempts(session_id) -> list[dict]`, ordered by number.
- `next_attempt_after(session_id) -> str | None`: the ISO date after the latest attempt's local date, or `None` when there are no attempts.
- `recording_state(topic_id) -> dict`, returning `{can_record: bool, reason: str | None, replace_number: int | None, next_number: int}`:
  - No thread: number 1 is allowed.
  - Latest attempt too short and not processing: replace it.
  - Today ≥ `next_attempt_after`: allowed.
  - Otherwise: reason "Next attempt opens tomorrow".
- `latest_checklist(session_id) -> list[str]`: the checklist from the latest review, or `[]`.

Endpoints:
- `GET /api/topics/{topic_id}/thread` returns `{topic, session_id, attempts:[attempt_public…], messages:[…with parts and attempt_number], recording:{…recording_state}, latest_checklist, next_attempt_after}`. With no thread, `session_id` is null and `attempts` is empty.
- `POST /api/topics/{topic_id}/attempts` takes multipart `file`, plus form fields `prompt_kind`, `style` and `duration`, validated as before.
  - It creates the thread only now, then the attempt with the next number or the replaced number, reusing the existing upload safety code.
  - It returns 409 with the reason when recording isn't allowed.
  - Each attempt stores `prompt_kind`, `style` and `duration` as new nullable attempt columns, added in Task 2 through the idempotent `_add_columns`. Legacy attempts fall back to their session's values.
- `GET /api/history` returns one row per thread: topic, attempt count, last attempt date, `can_record`, and the latest attempt's coverage.
- `GET /api/practice/ready` returns practised topics with a new attempt open, due first, each marked with `due: bool`.
- `GET /api/topics/recommend?include_practised=false` recommends from unpractised topics. With `true`, it recommends from all.
- `GET /api/sessions/{id}` keeps working and includes `topic_id`, so the frontend can redirect.

Removals:
- Remove `POST /api/sessions`, `PUT /api/sessions/{id}/stage`, `POST /api/sessions/{id}/attempts/{number}` and `GET /api/attempt2`.
- Chat, note, retry and rereview stay. `ChatInput.attempt_number` becomes any int ≥ 1 that must exist on the thread.

Pipeline:
- The structure pass's `previous_review` is attempt `number-1`'s review on the same thread. When `prompt_kind` differs, pass both prompts so the review can note that the angle changed.
- `after_review_written` reschedules the topic's spaced review for every attempt that has technical results. Too-short attempts don't reschedule. It replaces `complete_session`.
- Remove the stage and completion logic, and `complete_legacy_sessions`.

Tests:
- `test_picking_a_topic_creates_nothing`
- `test_first_upload_creates_thread_and_attempt_1`
- `test_same_day_new_attempt_refused_next_day_allowed`
- `test_too_short_latest_attempt_can_be_replaced_same_day`
- `test_attempt_3_gets_review_comparing_with_attempt_2`
- `test_chat_and_note_work_for_attempt_3`
- `test_history_lists_topics_with_recordings_only`
- `test_ready_lists_open_topics_due_first`
- `test_recommend_excludes_practised_unless_included`
- `test_each_reviewed_attempt_reschedules_spaced_review`

Steps:
- [ ] Write the tests and confirm they fail.
- [ ] Implement.
- [ ] Update the smoke harness to the new endpoints.
- [ ] Run the full suite and ruff.

### Task 3: Frontend topic threads

**Files:**
- Modify `frontend/src/App.tsx`, `Today.tsx`, `api.ts`, `types.ts`, `ReviewPage.tsx` and `Recorder.tsx`.
- Create `TopicPage.tsx` and `NewAttempt.tsx`.
- Tests: e2e, with mocks matching the real Task 2 responses exactly. Copy shapes from the backend tests.

Build:
- **Routing:** `#/topic/<id>` (optional `?attempt=N`) opens `TopicPage`. `#/session/<id>` fetches the session and redirects to its topic. Remove the stage stepper and the DayTwo screen.
- **`TopicPage`:**
  - Attempt pills, with the latest selected by default.
  - The selected attempt shows `ReviewPage`, which takes an attempt number and the thread data.
  - A "New attempt" button, or the disabled reason, for example "Next attempt opens tomorrow".
- **`NewAttempt`:**
  - Shows the topic, the question for the chosen question type, the "For next time" checklist (when any) and a "Try a different angle" select defaulting to the previous `prompt_kind`.
  - Shows no reviews, chat or references.
  - Uses the existing Recorder to upload to `POST /api/topics/{id}/attempts`. On success it goes to the topic page with the new attempt selected.
  - Cancel returns to the topic page.
  - For an unpractised topic it is the first screen, and it offers the existing duration and style options.
- **`Today`:**
  - Shows "Ready for another attempt" (with a "due" label), "Suggested topics" (unpractised only) and an "Include practised" pill. Practised entries open their topic page.
  - Shows "Pick up where you left off", linking to the most recent topic.
  - Removes the old "Second attempts" section and the "In progress" banner.
- **History:** topic rows from `/api/history`, linking to the topic page.

Tests:
- `picking a new topic records attempt 1 and lands on the topic page`
- `practised topic opens its topic page, never attempt 1`
- `attempt pills switch reviews and chats`
- `new attempt screen hides past feedback and offers a different angle`
- `new attempt disabled same day with reason`
- `today suggestions exclude practised unless include practised`
- `history lists topics only`
- `old session link redirects to topic`

Steps:
- [ ] Write the tests and confirm they fail.
- [ ] Implement.
- [ ] Run the build and the full Playwright suite twice.

### Task 4: Docs

- [ ] Update the README workflow and the AGENTS.md "Feedback pipeline" and "Interface" sections to describe topic threads. Remove the stage, day-2 and completion descriptions. No machine-specific values.
