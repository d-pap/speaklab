# Feedback and learning redesign

Status: draft for approval · 2026-11-16

## Why

SpeakLab records an impromptu technical explanation well, but its feedback and learning steps don't help. The learner records an attempt in SpeakLab and then pastes the transcript into a general-purpose chat assistant. That assistant's reviews do what SpeakLab's don't:

- respond to the learner's own read of the attempt
- remember the communication skills they are working on across days
- pick a few connected priorities instead of listing everything
- quote their exact words and rewrite them
- use the timestamps to show where the two minutes went
- correct technical nuance beyond a fixed concept list
- then teach the topic through a conversation the learner steers

The goal is for SpeakLab to do this itself, with every model running locally on a modest GPU (8 GB VRAM). The local-only constraint stays; making it work is part of the point.

The redesign replaces the structured rubric report and the prewritten lesson cards with a review the learner can talk to.

## Goals

1. After attempt 1, the learner gets a review comparable in usefulness to the reference reviews. It covers communication and technical substance, quotes and rewrites their words, and shows how the time was spent.
2. Learning happens in a conversation about the attempt, where the learner asks for the senior-engineer answer, simpler versions, alternatives or diagrams.
3. The coach remembers what the learner is working on and what they struggle with, and weights its feedback accordingly. No settings control is needed for this.
4. The key findings stay visible however long the conversation gets.
5. Attempt 2 happens on a later day and is reviewed against attempt 1.

## Non-goals for this version

- A review board that grows during the chat (pinned notes). Decide after real use.
- Hosted or cloud models. Everything stays on the host machine.
- Analysis of the voice audio itself by a model. The model gets measured summaries only.
- Fine-tuning, model upgrades, and running larger models on the GPU. That is a later project.
- The scoreboard comparing local reviews with reference reviews. That is the next project; see "Afterwards".
- New topic content, gamification and the colour palette.

## Anti-goals (failure even if it works)

- **A wall of metrics.** The current acoustic panels went unread because there was too much to interpret. Measurements are background, not the review.
- **Strict focus enforcement.** Focus areas weight the feedback but never become "the only thing to look for", and they have no fixed deadline.
- **Rubric grading that ignores what was said.** The review must engage with the actual transcript, not only check off reference concepts.
- **Invented measurements or quotes.** Every quoted line and every number must come from the transcript or the measurement code.
- **Agent or tool-loop infrastructure.** Small local models are weakest at long tool-calling loops, and an earlier decision rules this out.
- **Anything that sends audio, transcripts or notes off the host.**

## Constraints

- One GPU with 8 GB VRAM. Today the model runs at 8,192 tokens of context and 2,048 tokens of output (`backend/app/config.py`). One model is loaded at a time, unless two small ones fit together.
- Ollama for chat models and whisper.cpp for transcription, behind the existing replaceable adapters (`backend/app/models.py`).
- Recording, transcription and measurement must keep working when the model is unavailable, and a failed model step must never lose a recording. This is an existing decision.
- Each saved review keeps the model that produced it. This is an existing decision, extended here to every pass.
- The repository is public. Personal reference conversations and machine details stay outside it.

## Approaches considered

| | Approach | Trade-off | Outcome |
|---|---|---|---|
| A | One coach call writes the whole review and carries the chat | Simplest and closest to the reference assistant, but it asks a small model to do everything at once, the same overload that weakens today's `assess` | Not chosen; the passes in B can merge into this later if a stronger model makes it better |
| **B** | **Code measures; separate model passes analyse technical content and communication; a writer pass produces the review; one model carries the chat** | **Small models do better on one narrow job at a time, and a weak review can be traced to the pass that failed. Costs more latency (roughly one to two minutes per review) and more prompts** | **Chosen** |
| C | A tool-using agent (Hermes-style) that fetches lines and saves memory itself | Most flexible, but tool loops are where small local models fail, and it adds infrastructure that was ruled out | Rejected |

Two separate models (one technical, one communication) are an option inside B, not a separate approach. Every pass is its own model call and has its own model setting. All passes start on the same model. The scoreboard will decide whether a split helps.

## The design

### Session shape

- **Day 1:** record attempt 1, then the review and chat page.
- **A later day:** record attempt 2. Before recording, the learner sees the topic and the attempt 2 checklist from day 1, and nothing else from the review or chat. Attempt 2 should test what they remember, not repeat what they just read. Then a review and chat page for attempt 2, whose review compares it with attempt 1.
- **The learner's own read (optional).** After each recording, a small "How did that go?" box lets the learner write their own take, as they did when pasting transcripts elsewhere. Transcription, measurements and the technical and communication passes start immediately. Only the writer passes wait for the note to be submitted or skipped. If there's no answer within 5 minutes, it counts as skipped, so the review never waits indefinitely. The writer responds to the note, and the memory pass reads it.
- **Attempt 2 timing.** *Builder's call, recorded here:* attempt 2 becomes available from the next calendar day, and pending attempt 2s appear on the Today page. A pending attempt 2 never expires.
- **Completion and spaced review.** *Builder's call, recorded here:* the session completes automatically once attempt 2's review is generated. The again/hard/good/easy recall rating and the compare page are retired. The rating is derived from attempt 2's technical results through the existing `progress.mastery()`, so the technical pass keys its results to the `topics.json` concept IDs. Attempt 2 counts as the topic's first review. While attempt 2 is pending, the Today page shows only the attempt 2, not a separate spaced review for that topic. Incomplete sessions still don't count toward weak-topic recommendations.

### Review page layout

Desktop: two columns.

- **Left: tabs.**
  - **Transcript.** CapCut-style: one continuous text, with filler words highlighted inline ("um" and "uh" as fillers; "you know" and "I mean" lighter, as possible fillers, since they're sometimes meant) and pauses shown inline as small marks with their length, e.g. `went to, uh, um, [0.8s] the store`. A line timestamp appears where each line starts. A single quiet stats line sits above it: duration, filler count, pauses over 1 second, and the longest pause. This replaces the current separate plain and timestamped transcripts.
  - **Review.** Fixed findings from the attempt (it never changes during the chat):
    - scores, each with a one-line reason
    - three key points, each with time links
    - the attempt 2 checklist
  - **Measurements.** The existing acoustic and vocal displays, moved here and out of the way.
- **Right: coach chat.** The first message is the full review in the coach's voice. Time links in any coach message (`1:24`) jump to and highlight that line in the transcript.

Phone: the chat is the main view, and a control opens the transcript and review tabs.

### Scores

Scores out of 10, each with a one-line reason. They are labelled as coaching estimates, not measurements.

The core categories are clarity, structure, conciseness, technical accuracy, technical coverage and handling uncertainty, plus an overall score. The coach may add a score for a current focus area, such as natural playfulness.

Technical accuracy (what was said) and technical coverage (what wasn't reached) stay separate scores. This keeps the earlier rule that an omission is not an error.

*This revises the earlier "no numerical scores" rule.*

### Analysis pipeline (approach B)

Runs after transcription, in order. Each step is saved as it finishes, so a later failure keeps earlier results.

1. **Measurements (code, no model).**
   - Word-level timing comes from whisper.cpp. Pauses are gaps between words; fillers are detected from the existing filler list.
   - Transcript lines are stored with stable IDs and start times.
   - A short voice summary is written in plain sentences that tie numbers to lines, e.g. "longest pause 1.6s before line L7; pace slowed in the backend section". It does not dump every metric.
2. **Technical pass.**
   - Inputs: the transcript lines, the prompt, and the topic's curated reference from `topics.json`.
   - Output (structured): what was right, partial, wrong or missing; nuance corrections tied to line IDs; and the key points a senior engineer would cover.
   - Each point is labelled as supported by the reference or as the model's own knowledge. Points from the model's own knowledge are shown as "not in reference".
   - Omissions are distinguished from errors.
   - Any claim the pass marks wrong gets the existing bounded second check from `models.review_insights`. A correction that fails it is shown as unverified. This keeps the earlier decision on reviewing corrections, without a separate review pass.
3. **Communication pass.**
   - Inputs: the transcript lines, the voice summary and the coach notes.
   - Output (structured):
     - section boundaries by line ID, which code turns into a time-per-section breakdown
     - strengths and problems with line IDs and suggested rewrites, including more precise wording. This replaces today's separate vocabulary suggestions.
     - for each weak section, whether it looks like a knowledge gap or a communication gap
     - observations on the current focus areas
   - It uses the voice summary only where relevant. It leads with voice measurements only when a focus area is vocal.
4. **Review structure (writer, structured).**
   - Inputs: both analyses and the coach notes.
   - Output: the scores with reasons, three key points with line IDs, and the attempt 2 checklist.
   - For attempt 2, it also includes the score changes from attempt 1 and what changed.
5. **Review message (writer, prose).**
   - Expands the structure into the opening chat message.
   - Responds to the learner's own read of the attempt, if they wrote one.
   - Quotes their words, rewrites a few passages, gives an example of a strong answer, and ends with the main focus for next time.
   - Appears in the chat when it's finished, with a progress line until then. Chat replies stream; the review message doesn't, because it is written in the background while the learner may be away.

Validation carries over from today's code: every line ID must exist, and quotes are inserted from the transcript, never written by the model.

The rule also covers the streamed prose and every chat turn:
- The model never writes timestamps or the learner's words directly. It emits markers: `[[L7]]` for a time link, and `[[L7:"exact words"]]` to quote part of a line.
- The app expands markers while rendering. A marker with an unknown line ID is dropped. A quote that isn't an exact match within its line falls back to showing the whole line.
- Rewrites and example answers are the coach's own words and need no marker. A pass that returns invalid output gets one repair attempt. If it still fails, it is reported without blocking the steps that don't depend on it.

### Coach chat

- One model handles the whole conversation, with this context in a fixed order:
  - the system prompt
  - the coach notes
  - the transcript lines
  - the review structure
  - both analyses
  - the topic reference
  - the recent turns
- When the conversation outgrows the context budget, older turns are replaced by a running summary. The review, transcript lines and coach notes always stay in full.
- The chat is for learning: the senior-engineer answer, alternatives, simpler explanations and text diagrams.
- The current prewritten lesson cards, recall checks and tutor drawer are retired from the flow. The curated topic reference stays as grounding.

### Coach notes (memory)

- A short plain-text document about the learner. It covers:
  - current focus areas, with evidence and since when
  - recurring struggles
  - goals they have stated
  - how they like to be taught
- The memory step is a separate model pass that rewrites the notes from the old notes plus the new material.
- When it runs: before each review is generated, it folds in every session and chat since the last update. The review therefore always sees what the learner said last time.
- It picks up things the learner states ("I'm working on keeping things light") and patterns the coach observed.
- When a focus area shows consistent progress, it notes that and suggests what might come next. It never removes a focus area on its own.
- Every version is kept. A "What your coach remembers" page in Settings shows the current notes, lets the learner edit them, and can restore an earlier version. A word cap (around 400) keeps the notes from growing without limit.

### Model settings

- Each pass has its own model setting in Settings: technical, communication, review writer, chat and memory.
- All default to the current model.
- Only installed local models are eligible. This is the existing rule.
- Context and output limits become per-pass settings with the current values as defaults. The exception is the review writer, which defaults to 4,096 output tokens, because a full review runs to about 3,000.

### Existing sessions

Earlier sessions stay readable. *Builder's call:* show them in the new layout with their old assessment summarised in the Review tab, plus a button to re-review the attempt with the new pipeline. Re-reviewing keeps the earlier analysis, following the existing `analysis_history` pattern. It replaces the old reanalyze action.

## Definition of done

- The full pipeline runs on the host's real models and passes validation on saved attempts.
- Prompts have been tuned against the reference reviews. These are kept privately, outside the repository, in the gitignored `.local/reference-reviews/`.
- The learner has used it on real attempts and judged the reviews and chat useful.

The scoreboard that turns "comparable to the reference" into a number is the next project.

## Left to the builder

- **Word timing.** Whether the whisper.cpp server returns word timestamps in the needed form, or whether it must be run with different options. If it can't, fall back to pauses at line boundaries only.
- **Pause and filler thresholds** for the inline marks.
- **Prompt wording** for each pass, and the exact JSON schemas.
- **Latency and VRAM.** Actual latency and VRAM per pass on the host, and whether to raise context or output limits. A review over about 3 minutes, or out-of-memory errors, should be reported back, not silently worked around by dropping passes.
- **Progress display** while passes run, e.g. "Reading the technical side… the communication side… writing".
- **Data model changes:**
  - attempt 2 on a different day than attempt 1
  - transcript line IDs
  - per-pass results
  - the review structure
  - coach-note versions
  - per-pass model settings

## Afterwards (not this project)

1. **Scoreboard.** A private set of transcripts with reference reviews. New local reviews are compared side by side without knowing which is which, so "as good as the reference" becomes a number. Run it on the old and new SpeakLab to get the first result.
2. **Model work.**
   - larger models on the 8 GB GPU, e.g. mixture-of-experts models with part of the model offloaded to system RAM
   - per-pass model choices
   - fine-tuning, each measured against the scoreboard
3. **Decide after use:** a review board that grows during the chat, and model analysis of the audio itself.
