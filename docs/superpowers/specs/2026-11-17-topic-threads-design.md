# Topic threads: one ongoing practice thread per topic

Status: decided 2026-11-17 (the learner delegated the remaining decisions)

## Why

The first redesign kept the old model: every topic click created a new session with exactly two attempts and a fixed stage machine. In real use this caused four problems:

- Re-opening a practised topic started a new attempt 1.
- A session could lock the learner on the attempt-2 screen with no way back to their feedback.
- Topic clicks without a recording filled History with empty sessions (11 of 21 on the host).
- A topic could appear as both "Second attempts" and "Suggested" on Today.

The learner wants to come back to a topic, reread and continue the feedback and coaching, and record more attempts on later days, with no limit.

## The model

- **A topic thread.** Each topic has at most one practice thread. The existing `sessions` table row is the thread, and its `stage` and `completed_at` columns are no longer used.
- **Lazy creation.** A thread is created only when the first recording is uploaded. Picking a topic creates nothing.
- **Attempts.** Attempts are numbered 1, 2, 3 and so on, with no upper limit. Each attempt stores its own question type (`prompt_kind`), with the prompt text derived from it, plus its own style and duration.
- **Each attempt keeps its own:** transcript, analysis, review, note and coach chat. Chats stay per attempt, which keeps model context small. Coach notes carry memory across attempts and topics.
- **When a new attempt opens:** from the calendar day after the latest attempt, without limit. If the latest attempt was too short to review, it can be re-recorded (replaced) the same day.
- **Comparison.** Each attempt's review compares with the previous attempt's review, generalising the earlier attempt-1/attempt-2 comparison. When the question type changed, the review says so, and the score changes are read as indicative.
- **Spaced review.** After each attempt's review, the topic's spaced-review date is rescheduled from that attempt's technical results, using the existing `progress.schedule` and `derived_recall`.

## Screens

- **Topic page** (`#/topic/<topic_id>`):
  - Shows a row of attempt pills ("Attempt 1 · Attempt 2 · …") with the latest selected.
  - The selected attempt shows the existing review page: Transcript, Review and Measurements tabs plus its coach chat.
  - Any attempt can be revisited, and its chat continued.
  - A "New attempt" button is enabled when a new attempt is open; otherwise it shows "Next attempt opens tomorrow".
- **New-attempt screen.** This is a clean recording screen:
  - It shows the topic, the question and the latest attempt's "For next time" checklist.
  - It never shows past reviews, chat or references.
  - It offers "Try a different angle", a question-type select that defaults to the previous attempt's question.
  - Cancel returns to the topic page.
- **First attempt on a new topic.** Picking an unpractised topic opens the same recording screen. The thread appears only after the upload.
- **History** lists topics, not sessions: one row per topic with at least one recording, showing title, number of attempts, last attempt date and whether a new attempt is open.
- **Today:**
  - "Ready for another attempt" lists practised topics where a new attempt is open. Spaced-review-due topics come first, labelled "due", then the oldest last attempt.
  - "Suggested topics" lists only topics never recorded.
  - An "Include practised" pill adds practised topics to suggestions and topic browsing. Choosing a practised topic opens its topic page and never starts a new attempt 1.
  - A "Pick up where you left off" link goes to the most recently active topic.
- **Old links.** `#/session/<id>` links redirect to the topic page.

## Existing data

- The migration takes the schema to v5.
- It rebuilds `attempts` without the `number IN (1,2)` check.
- It merges each topic's sessions that have recordings into the earliest such session. Attempts are renumbered by date, and their messages and history follow them.
- Sessions without recordings are kept but never listed.
- Legacy reviews keep their old summary and re-review button.

## Non-goals

- No change to the coach passes, prompts or models, beyond generalising the previous-attempt comparison.
- No cross-attempt chat.
- No same-day extra attempts, apart from replacing a too-short attempt.
