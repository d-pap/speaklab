# SpeakLab

Impromptu speaking practice for technical topics. Pick a topic, explain it out loud with no preparation, get local AI feedback on content and delivery, then explain it again. Everything runs on your own machine: recordings, transcripts and models never leave it.

React + TypeScript + Vite + Tailwind · FastAPI + Pydantic · SQLite · Ollama · whisper.cpp · NumPy + Praat

SpeakLab runs on one Mac or Linux machine, as described below. To host it on a Windows PC with a GPU and practice from another computer or a phone, see [Deploying SpeakLab on a Windows PC](docs/deployment.md).

## Quick start

Requirements: macOS/Linux, Python 3.11+ (3.12 recommended), Node.js 22+, and a current browser. Chromium is used for automated microphone tests. No account or API key is required.

From the project root:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements.lock
uv pip install --python .venv/bin/python --no-deps -e backend
npm --prefix frontend ci
cp .env.example .env
python3 scripts/dev.py
```

Without `uv`, use `python3 -m venv .venv` followed by `.venv/bin/python -m pip install -e './backend[dev]'`.

Open **http://127.0.0.1:5173**. The API runs on **127.0.0.1:8765**. Ctrl-C stops both application servers.

The dependency installation and model downloads need internet. Once installed, the runtime uses local assets and loopback services only. Without models you can still record, replay, transcribe (if Whisper is running), see measurements and schedule the next attempt. Missing AI feedback is explicitly marked unavailable.

Separate-terminal commands, if preferred:

```sh
# Terminal 1, project root
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# Terminal 2, project root
npm --prefix frontend run dev
```

`npm --prefix frontend run build` creates a production frontend. Set `SPEAKLAB_SERVE_FRONTEND=true` to serve that build directly through FastAPI on port 8765, as a deployed host does. Vite preview also uses port 4173; do not start it while a [remote-host tunnel](docs/deployment.md#how-to-connect-from-a-mac-with-the-ssh-tunnel) uses that port. This is a single-user app: keep the listeners on loopback and use authenticated tunneling for remote access.

## Local models

### 1. Ollama / Qwen

Install [Ollama](https://ollama.com/download), then download the default model:

```sh
ollama pull qwen3.5:9b-q4_K_M
```

Start Ollama if it is not already running:

```sh
OLLAMA_NO_CLOUD=1 ollama serve
```

The default is `qwen3.5:9b-q4_K_M`, tested on an 8 GB NVIDIA GPU. SpeakLab disables thinking for bounded JSON passes, uses an 8K context (4096 output tokens for the review writer, 2048 for the other passes), and runs Whisper on CPU to preserve GPU memory. The smaller Qwen3 8B remains configurable, but failed a structured claim-review case that Qwen3.5 handled correctly. These small calibration tests do not establish general factual reliability.

In **Settings → Model for feedback & coaching**, select an installed model and click **Use model**. Five passes (technical review, communication review, review writer, chat and coach notes) each have their own model, context and output settings, which all start on that model. **Refresh models** finds new downloads in the connected Ollama service. The choices persist in the database and override the initial `SPEAKLAB_OLLAMA_MODEL` default; no app restart is needed. Changes wait for active analysis and coach replies to finish. Every saved pass result keeps the model that produced it. The picker does not download models or change Whisper. A small local model can still return invalid structured output; a failed pass shows an error with Retry and keeps the earlier passes.

Only downloaded local models are supported. SpeakLab rejects cloud tags and models advertising remote routing, disables HTTP proxy inheritance and redirects, and accepts model URLs only on loopback. Also keep Ollama's cloud features disabled with `OLLAMA_NO_CLOUD=1` in the environment of the Ollama process. A GUI-managed Ollama process needs that setting applied to that process separately.

### 2. whisper.cpp

The adapter targets the [whisper.cpp HTTP server](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server), posting 16 kHz mono PCM WAV to `/inference` with `response_format=verbose_json`. It does not use browser cloud speech recognition.

On Apple Silicon, install Xcode Command Line Tools if needed (`xcode-select --install`) and CMake (`brew install cmake`). In a separate tools directory:

```sh
mkdir -p ~/dev/tools
cd ~/dev/tools
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON -DWHISPER_BUILD_SERVER=ON
cmake --build build --config Release -j 4
bash ./models/download-ggml-model.sh small.en
./build/bin/whisper-server -m models/ggml-small.en.bin --host 127.0.0.1 --port 8080
```

`small.en` is the recommended model. On a two-minute saved sample it transcribed in about 13 seconds; both base.en and small.en retained all four scripted hesitations in a synthetic test. This does not prove complete natural filler detection. The server must support `prompt`, `suppress_non_speech`, `token_timestamps`, `split_on_word`, and verbose JSON segment words (the deployed whisper.cpp build does). No cloud transcription is used.

SpeakLab decodes browser audio itself using a bundled FFmpeg binary from `imageio-ffmpeg`, so whisper-server does not need `--convert`. Keep whisper VAD disabled for the initial setup: the acoustic pause timeline and transcript segments should refer to the original recording timeline.

Open **Settings → Check local services**. Ollama readiness checks the configured model; Whisper status checks service reachability, not successful inference. Real transcription failures are reported on the attempt with a retry action.

## Vocal foundations and variation

On the review page, open **Measurements → Voice measurements → Vocal variation** and choose Rate, Volume, Pitch & melody, Pauses or Tonality. Playback markers jump to the measured passages.

- Rate compares full 30-second WPM estimates from timestamped transcripts. WPM includes pauses; distributing words across transcript segments can miss changes within a sentence. Manual transcripts cannot supply aligned pace variation.
- Volume compares P10–P90 loudness spreads within full, usable 15-second active-audio windows. It does not compare calibrated speaking loudness, and the least varied window is not necessarily the quietest. Microphone movement, gain and processing affect the recording.
- Pitch compares P10–P90 semitone spreads within full 15-second voiced windows, with the estimated pitch contour available separately. Tracking can fail; a narrow range does not establish monotone delivery. See [Praat’s pitch guidance](https://praat.org/manual/Intro_4_2__Configuring_the_pitch_contour.html).
- Pauses show internal energy-gap locations, durations and a timeline. Leading/trailing silence is excluded from the internal-pause total, and these markers do not establish a word boundary or communicative purpose.
- Tonality is a listening and intention exercise. The app does not infer emotions, confidence, charisma or audience engagement.

Variation is descriptive, without an ideal range or a higher-is-better score. Only comparable full windows are included; missing data remains unavailable. The explorer reads existing stored measurements, so it does not require a model call or additional audio copies. Short/older recordings may not contain sufficient temporal data.

## Daily workflow

1. **Pick a topic.** Use the weighted random suggestion or choose from 16 curated topics across eight categories and three levels. Choose 2–5 minutes, a prompt type, and an intended delivery style. Each topic has one ongoing practice thread. Picking a topic you have not practised opens a clean recording screen, where you choose the speaking time, question type and delivery style before recording (the time and style are remembered in the browser for the next first attempt); nothing is created until the first recording is saved. Picking one you have practised opens its topic page.
2. **Explain from memory (attempt 1).** Record with the browser microphone. Pause/resume, stop early, listen, re-record before saving, or import WAV/WebM/Ogg/MP4 audio. The countdown excludes manually paused time. Reference material is unavailable until the cold recording is saved.
3. **Review and chat.** Audio is stored before analysis begins. The review page has the transcript, review and measurements on the left and the coach chat on the right. A small **How did that go?** box lets you write your own read of the attempt; send it or skip it (it counts as skipped after five minutes). The coach opens the chat with a written review that quotes your words, rewrites a few passages, shows how the time was spent and ends with a main focus. The Review tab keeps the fixed findings: scores out of 10 with a one-line reason each, three key points with time links, and your checklist for next time. The Transcript tab shows one continuous text with filler words and pauses marked inline; time links in the coach's messages jump to and highlight the line. Edit transcription errors if necessary; edits clear the old analysis and rerun it. A recording with almost nothing in it gets no scores and a prompt to record again.
4. **Learn by asking.** The chat is where you learn: ask for the senior-engineer answer, a simpler version, alternatives and trade-offs, or a text diagram, and explain an idea back to get feedback. The coach will not hand over a script to memorise. Long conversations are summarised for the model, but your review, transcript lines and coach notes always stay in full.
5. **Come back for another attempt.** A new attempt opens from the calendar day after your latest one, so it tests what you remember, and there is no limit on how many you record. On the topic page, **New attempt** opens a clean recording screen with only the topic, the question and your "For next time" checklist; past reviews, chat and references stay hidden until you save. **Try a different angle** lets you pick another question type, defaulting to the last one. Each attempt gets its own review and chat. The review compares with the previous attempt and says when the question type changed, so score changes are only indicative. Saving each review reschedules the topic's next spaced review. There is no rating to enter. If your latest attempt was too short to review, you can record it again the same day.

The **topic page** (`#/topic/<topic id>`) shows a row of attempt pills with the latest selected. Any attempt can be reopened, with its transcript, review, measurements and chat, and its chat continued. When no new attempt is open yet, the button reads "Next attempt opens tomorrow".

On **Today**, "Ready for another attempt" lists practised topics with a new attempt open: spaced reviews that are due first (marked "due"), then the oldest last attempt. "Suggested topics" lists only topics you have never recorded; the **Include practised** pill adds practised ones to suggestions and topic browsing. "Pick up where you left off" goes to the most recently active topic. **History** has one row per practised topic with its attempt count, last attempt date and whether a new attempt is open. Old `#/session/<id>` links redirect to the topic page. Raw audio is preserved. Processing runs in one background worker to avoid loading several analysis jobs at once; after a server interruption, recordings remain saved and interrupted jobs can be retried. An attempt with feedback cannot be overwritten; only a too-short latest attempt can be replaced. If a pass fails, the transcript, measurements and earlier passes stay visible and Retry re-runs only the failed and later passes. Sessions recorded before the coach existed keep their old assessment summary and offer **Re-review this attempt**, which keeps the earlier analysis.

### Coach notes

The coach keeps short notes about you: the skills you are working on, recurring struggles, goals you have stated and how you like to be taught. Before each review a separate pass folds in the sessions and chats since the last update. The review is weighted toward your focus areas without ignoring everything else, and the notes never drop a focus area on their own. **Settings → What your coach remembers** shows the current notes (about 400 words at most), lets you edit them and restore any earlier version.

### Coaching feedback

Use the thumbs below a written review or learning-chat reply to mark it helpful or unhelpful. Optionally add what worked or missed the mark, a reason such as a missed insight or wrong diagnosis, and what a better response would say. Click the selected thumb to remove your feedback.

The **Coach model** picker above the conversation selects an installed local model for new reviews and replies across SpeakLab. Choose a model, then click **Regenerate review** to rerun the complete review for the saved attempt. Existing chat, ratings, recordings and review dates are preserved. **View previous reviews** opens the archived written feedback and its model; each current coach response also identifies the model that produced it. Custom per-step models remain in Settings and are left intact until you explicitly choose a common model. Finish an active review or reply before switching models or regenerating.

Feedback stays in the local database, with the original response and its available generation context preserved through transcript edits and re-reviews. **Settings → Coaching feedback → Export feedback** downloads these records. Votes collect evidence for improvement; they do not automatically train or switch models. Private reference conversations can also supply examples of useful observations and teaching, after checking their completeness and separating training from evaluation. See [Improving local coaching](docs/coaching-feedback.md).

## What works

| Area | Implemented behavior |
| --- | --- |
| Topic catalog | 16 original reference summaries, 68 reference concepts, sources, 8 categories, 3 difficulties, 6 prompt types |
| Recording | Browser MediaRecorder; real input activity; timer; pause/resume; playback; re-record before save; import; local download |
| Storage | SQLite topic threads (the sessions table), unlimited attempts, messages, reviews, coach notes; original audio plus decoded analysis WAV; stable UUID filenames |
| Transcription | whisper.cpp adapter; segments and word timing where supplied; manual correction; independent retry |
| Review pipeline | Separate technical, communication and writer passes on local models; each pass saved as it finishes with its model; retry from the failed pass; validated line IDs; no model-written quotes or times |
| Review page | Transcript with inline fillers and pauses, fixed review (scores, key points, checklist for next time), measurements, streamed coach chat with time links |
| Audio | Relative loudness, P10–P90 spread, energy-based activity and internal pauses, extended silence, Praat pitch contour and spread |
| Transcript metrics | WPM, limited filler-phrase counts, approximate 30-second speaking-rate windows when timestamps exist |
| Coach notes | Memory pass with versioned, editable notes |
| Topic threads | One thread per topic, created at the first recording; unlimited attempts, each with its own review and chat; a new attempt opens the next calendar day; clean recording screen; review compares with the previous attempt and notes a changed question type |
| Retention | Spaced-review date rescheduled after each attempt from its technical results, weighted recommendations, history by topic |
| UI | Responsive layouts, light/dark mode, labeled controls, keyboard focus, reduced-motion support, meaningful unavailable/loading states |

The 68 concept count includes eight neural-network concepts; other topics have four. Reference content is original concise teaching material with links to supporting documentation, not downloaded at runtime.

## Measurements and rubric

- **Scores:** out of 10 in half steps with a one-line reason, labelled coaching estimates, not measurements. Overall, Clarity, Structure, Conciseness, Technical accuracy, Technical coverage and Handling uncertainty, plus optional scores for a current focus area. Accuracy (what was said) and coverage (what was not reached) are separate, so an omission is not treated as an error. A verbatim quote proves the words were said, not that the model's interpretation is correct. Technical points are labelled as in the topic reference or the model's own knowledge.
- **Rate:** transcript word count / recording duration in minutes, including pauses. Segment rates distribute segment word counts across overlapping 30-second windows and are approximate. Manual transcript edits clear segment timing, so segment-rate charts become unavailable.
- **Fillers:** `um`, `uh`, `erm` and `er` are counted as fillers; `you know` and `I mean` are marked lighter as possible fillers because they are sometimes meant. Ambiguous `like`, `so`, `actually` and similar words are not counted. Transcription can remove disfluencies. Counts are not a quality grade.
- **Activity and pauses:** 30 ms RMS windows with 10 ms hops; an adaptive energy threshold; short gaps bridged. Internal low-energy gaps ≥0.3s count as pauses. Low-energy runs ≥2s also appear as extended silences, including the recording edges. This is not a learned speech detector: background noise and soft speech affect it.
- **Loudness:** RMS in relative dBFS and active-frame P10–P90 spread. This is not calibrated physical loudness. Microphone placement, room noise, browser processing, and gain confound comparisons.
- **Pitch:** Praat autocorrelation over 60–500 Hz; median and P10–P90 range in semitones. Unvoiced regions are gaps. Out-of-range voices, creak, noise, and octave errors can distort results. Pitch failure leaves other measurements usable.
- **Delivery:** the coach receives a short written voice summary, not the raw arrays, and leads with voice only when a focus area is vocal. Suggestions are tentative. Faster, louder, or more variable is never automatically scored as better. Articulation, vocal archetypes, tonality, narrative quality, and audience engagement are not reliably established by these measurements.

Review intervals start at 1 / 2 / 3 / 7 days for again / hard / good / easy. They are derived from the share of reference concepts an attempt fully demonstrated in the technical pass; there is no manual rating, and only the latest attempt's review reschedules the topic, once. Repeated successful reviews expand the interval, capped at 90 days. Less than 50% fully demonstrated caps the result at again; less than 80% caps easy at hard. This is a deliberately simple heuristic, not a validated mastery estimate.

## Configuration and data

Copy `.env.example` to `.env` at the project root. Configuration is read at backend startup.

| Variable | Default |
| --- | --- |
| `SPEAKLAB_DATA_DIR` | `./data`, relative to the project root |
| `SPEAKLAB_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `SPEAKLAB_OLLAMA_MODEL` | `qwen3.5:9b-q4_K_M` |
| `SPEAKLAB_WHISPER_URL` | `http://127.0.0.1:8080` |
| `SPEAKLAB_OLLAMA_CONTEXT` | `8192` tokens, the default for every pass |
| `SPEAKLAB_OLLAMA_MAX_OUTPUT` | `2048` tokens, the default for every pass except the review writer (`4096`) |
| `SPEAKLAB_SERVE_FRONTEND` | `false`; set true after building `frontend/dist` |
| `SPEAKLAB_SERVER_NAME` | `This computer`; the name shown in Settings |
| `SPEAKLAB_MODEL_TIMEOUT` | `180` seconds per model call; one repair call may follow |
| `SPEAKLAB_MAX_UPLOAD_BYTES` | `31457280` (30 MiB) |

The frontend proxy defaults to `http://127.0.0.1:8765`; set `SPEAKLAB_API_TARGET` when launching Vite if you change the backend port. Browser origins are explicitly allowed for local application/test ports. Use `localhost` or `127.0.0.1`, not a LAN IP.

`data/speaklab.sqlite3` contains structured data and `data/recordings/` contains audio. SQLite schema migrations run in place and newer unknown schema versions fail explicitly. Schema v5 removed the two-attempt limit and merged each topic's recorded sessions into one thread, renumbering attempts by date; sessions with no recording are kept but never listed. `analysis_history` archives earlier analysis snapshots when an attempt is re-reviewed; `app_settings` stores the selected models and per-pass settings; coach notes keep every version. Original audio and review dates are preserved. To back up, stop the backend and copy the entire data directory, including any SQLite sidecar files. Moving a backup to another machine currently requires updating the absolute recording paths in SQLite. Browser-local state is limited to the theme and the speaking time and style last chosen for a first attempt; chat messages are stored in SQLite.

No telemetry, external fonts, model SDK callbacks, or remote assets are loaded by the app. Opening a source link is an explicit navigation to that external site. Data is not encrypted by the application; use your operating system's disk protection and normal backups. Audio filenames ignore supplied filenames, containers are checked by signature and decoder, input is bounded to 30 MiB / six minutes, and FFmpeg receives only local generated paths without a shell. Recordings shorter than 0.5 seconds are rejected.

## Tests and development

```sh
# Core logic + real API/database/audio integration; model services are explicit test doubles
.venv/bin/python -m pytest backend/tests -q
.venv/bin/ruff check backend

# Type-check and production build
npm --prefix frontend run build

# Browser tests (install Chromium once)
cd frontend
npx playwright install chromium
npm test
```

Browser tests start dedicated services on 8766 and 5174, use `data/e2e` (emptied at the start of each Playwright run, never practice data), and intentionally point model adapters at an unavailable loopback port. They exercise the actual API and DSP, browser recording with Chromium's fake microphone, denial recovery, uploads, manual transcription, the review page and coach chat with their unavailable states, next-attempt timing, topic threads, history by topic, reload persistence, mobile layout, and theme. Synthetic audio and test responses exist only in test/diagnostic code. Browser tests never reuse a running normal server. Test data is separate from practice data.

Backend tests cover structured-output repair, topic-specific concept schemas, per-pass model settings, line-ID and marker resolution, aggregated validation errors, partial failures and retry, chat context budgeting, coach notes, local-only service configuration, blocked remote Ollama models, transcript invalidation, topic-thread timing and the v5 merge, known-frequency pitch and known-duration pauses, silent audio, upload rejection/cleanup, interrupted jobs, and review scheduling.

OpenAPI is available at `http://127.0.0.1:8765/docs`. Frontend domain contracts live in `frontend/src/types.ts` and the model picker component; incoming requests and model output contracts live in `backend/app/schemas.py`. Runtime logs are JSON events containing route templates and processing identifiers; transcripts and audio are not logged.

```
backend/app/
  main.py          API routes and local request boundary
  db.py            SQLite schema and persistence helpers
  curriculum.py    Safe public catalog, prompts, recommendations
  topics.json      Curated concepts, examples and sources (the reference that grounds the passes)
  audio.py         Decode, DSP, transcript metrics, delivery exercises
  models.py        Loopback whisper/Ollama adapters
  llm.py           Per-pass model settings, context budget, structured and streaming calls
  coach.py         Technical, communication, review structure and review message passes
  chat.py          Coach chat context, summaries and streaming replies
  memory.py        Versioned coach notes and the memory pass
  markers.py       Resolves [[L7]] / [[L7:"words"]] markers against stored lines
  transcript.py    Transcript lines, inline filler and pause tokens, stats
  voice.py         Plain-sentence voice summary for the passes
  threads.py       Topic threads: next-attempt timing, replaceable too-short attempt, latest checklist
  pipeline.py      Durable attempt states and serialized background processing
  progress.py      Review intervals and mastery from an attempt's technical results
  schemas.py       Pydantic request and pass-output contracts
frontend/src/
  App.tsx          Navigation, topic library, history by topic, settings
  TopicPage.tsx    One topic's attempts: pills, review page, new-attempt entry
  NewAttempt.tsx   Clean recording screen: question, checklist, question-type select
  Recorder.tsx     Browser audio lifecycle and recording workspace
  ReviewPage.tsx   Review page: tabs, note box, chat, mobile sheet
  ReviewTab.tsx    Scores, key points, checklist for next time
  TranscriptTab.tsx Inline fillers and pauses, line highlight
  CoachChat.tsx    Streamed coach chat with time links
  CoachNotes.tsx   View, edit and restore coach notes
  Practice.tsx     Acoustic panel and attempt status
  Today.tsx        Practice starting point, topics ready for another attempt, suggestions
  components.tsx   Shared UI and measurement charts
  types.ts         Typed API/domain contracts
scripts/dev.py     Local development launcher
```

## Current limits and next steps

- Real Qwen/Whisper inference has passed a complete synthetic-speech integration run on a Windows/WSL host, including two attempts. That run predates the coach pipeline; its separate passes and chat have not yet been timed on the host (see `scripts/smoke-inference.py`). Passing integration does not establish review quality on arbitrary speech. Natural speech, more topics, and standalone Apple Silicon performance still need calibration.
- Technical judgments can be wrong even with valid JSON and genuine excerpts. The curated reference is the baseline; especially for audience-specific prompts, review whether omitted concepts were actually essential.
- The coach reviews each attempt in several local passes, so a review takes longer than a single call (the design target is one to two minutes). Prompt quality on real attempts is still being tuned.
- Pause detection is energy-based, pitch is an estimate, and filler detection is transcript-based. There is no emotion, confidence, charisma, video, or reliable automatic articulation scoring. Vocal archetypes are treated as delivery intentions, not classified identities.
- Review scheduling and longitudinal tracking are a basic foundation. History shows per-session measurements; advanced trend charts, calibrated mastery, and more adaptive scheduling remain future work.
- Audio is saved to disk when you choose Save. Until then it is held in the browser; closing the page can lose it. The UI warns on normal navigation and provides a download fallback after an upload failure. There is no IndexedDB crash recovery or offline-service-worker installation.
- Browser imports can include video containers, but only the first audio stream is analyzed. No video is recorded or evaluated.
- Single user and one backend process only. Jobs run serially in memory and become retryable after restart. There is no cancellation UI, deletion/export interface, or multi-device synchronization. Backups are manual; `scripts/backup-data.sh` provides a verified-archive workflow for a [deployed host](docs/deployment.md#how-to-back-up-and-restore-practice-data).
- Mic behavior has automated Chromium coverage and saved natural desktop-browser recordings; Safari/Firefox still need hands-on verification. Keep consistent mic placement and permissions when comparing recordings.

Useful next work: hands-on speech calibration, unattended Windows reboot verification, scheduled backups, broader topic depth, adaptive study checks, a proper local speech activity detector, accessibility auditing with assistive technology, and retention trends across several weeks of real practice.


## Feedback details

- **Transcripts:** local Whisper receives a disfluent example prompt with non-speech suppression off. The original recognized text is retained. Verbatim-oriented does not mean guaranteed verbatim: omissions and hallucinations remain possible. Word timing is used when the server supplies it, with segment-start fallbacks. Measured audio pauses appear inline, including pauses inside speech segments, without pretending to know an exact word boundary.
- **Fillers:** um/uh/erm variants are counted, with counts per minute. "You know" and "I mean" are shown as possible fillers. "Like," "so," "actually," "basically" and "right" are context-dependent and not counted as definite fillers. Exact repeated words are shown separately; intentional emphasis is not automatically penalized.
- **Technical review:** one pass compares the transcript with the curated topic reference and the model's own knowledge. Points are labelled as in the reference or not. Missing concepts remain separate from false claims. A correction the pass proposes gets a second bounded check and shows as unverified if it fails. This is not independent verification.
- **Communication review:** one pass finds sections, strengths, problems and rewrites, and says whether a weak section looks like a knowledge gap or a communication gap. A rewrite is the coach's own wording; check it yourself.
- **Evidence:** the models cite transcript lines by ID. The app inserts the learner's words and line times itself, so a quote or time that was not in the recording cannot appear.
- **Vocal foundations:** five practice cards explain rate, relative volume, pitch/melody, pauses, and intended tonality. Fifteen-second audio windows identify passages to replay; pitch is only compared with enough voiced samples. No universal variation targets, emotion detection, facial-expression inference, or charisma scores. Rate windows are estimates; noise, mic gain and automatic processing limit comparisons.
- **Reading level:** optional approximate Flesch–Kincaid US grade band; minimum 100 words and three punctuated sentences. The displayed formula uses heuristic syllable counting on a separate copy with detected hesitations removed. It is not a vocabulary/ability score or a target to maximize. Speech fragments, jargon and ASR punctuation can distort it.
- **Topic reference:** all 16 topics include brief background, per-concept prerequisite bridges, and a concise engineering-practice paragraph with curated source links. It grounds the review and chat and is available offline.

Re-reviewing a saved attempt runs the current pipeline again and keeps the earlier analysis. Re-reviewing does not reschedule the topic again.

Validation includes explicit test doubles for malformed evidence and model failures, database upgrade and snapshot preservation, synthetic pitch/pause audio, mobile/browser playback and disclosures, and a separate real-inference calibration on a deployed host. Test data is never inserted into practice history.
