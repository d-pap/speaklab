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

The dependency installation and model downloads need internet. Once installed, the runtime uses local assets and loopback services only. You can immediately record, replay, study reference lessons, and schedule reviews without models. Missing AI feedback is explicitly marked unavailable.

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

The default is `qwen3.5:9b-q4_K_M`, tested on an 8 GB NVIDIA GPU. SpeakLab disables thinking for bounded JSON reviews, uses an 8K context, and runs Whisper on CPU to preserve GPU memory. The smaller Qwen3 8B remains configurable, but failed a structured claim-review case that Qwen3.5 handled correctly. These small calibration tests do not establish general factual reliability.

In **Settings → Model for feedback & tutoring**, select an installed model and click **Use model**. **Refresh models** finds new downloads in the connected Ollama service. The choice persists in the database and overrides the initial `SPEAKLAB_OLLAMA_MODEL` default; no app restart is needed. Switching waits for active analysis/tutoring to finish. Existing feedback keeps its recorded model; use explicit reanalysis to assess it with another model. The picker does not download models or change Whisper. A local chat model may still fail structured assessment; retry or choose a tested model.

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

In feedback, open **Communication & voice → Vocal variation** and choose Rate, Volume, Pitch & melody, Pauses or Tonality. The same explorer is available under each attempt in the comparison view. Playback markers jump to the measured passages.

- Rate compares full 30-second WPM estimates from timestamped transcripts. WPM includes pauses; distributing words across transcript segments can miss changes within a sentence. Manual transcripts cannot supply aligned pace variation.
- Volume compares P10–P90 loudness spreads within full, usable 15-second active-audio windows. It does not compare calibrated speaking loudness, and the least varied window is not necessarily the quietest. Microphone movement, gain and processing affect the recording.
- Pitch compares P10–P90 semitone spreads within full 15-second voiced windows, with the estimated pitch contour available separately. Tracking can fail; a narrow range does not establish monotone delivery. See [Praat’s pitch guidance](https://praat.org/manual/Intro_4_2__Configuring_the_pitch_contour.html).
- Pauses show internal energy-gap locations, durations and a timeline. Leading/trailing silence is excluded from the internal-pause total, and these markers do not establish a word boundary or communicative purpose.
- Tonality is a listening and intention exercise. The app does not infer emotions, confidence, charisma or audience engagement.

Variation is descriptive, without an ideal range or a higher-is-better score. Only comparable full windows are included; missing data remains unavailable. The explorer reads existing stored measurements, so it does not require reanalysis, a model call or additional audio copies. Short/older recordings may not contain sufficient temporal data.

## Daily workflow

1. **Pick a topic.** Expand **Practice settings** to change duration, prompt style or delivery intention. Use the weighted random suggestion or choose from 16 curated topics across eight categories and three levels. Choose 2–5 minutes, a prompt type, and an intended delivery style.
2. **Explain from memory.** Record with the browser microphone. Pause/resume, stop early, listen, re-record before saving, or import WAV/WebM/Ogg/MP4 audio. The countdown excludes manually paused time. Reference material is unavailable until the cold recording is saved.
3. **Reflect.** Audio is stored before analysis begins. Inspect separate technical and voice panels. Missing concepts are distinct from inaccurate claims. Each non-missing concept and transcript coaching point must quote actual transcript text. Edit transcription errors if necessary; edits clear the old assessment and timing alignment and rerun analysis.
4. **Learn.** Read one curated section at a time, selected around first-attempt gaps. **Check your understanding** switches to a recall view with the notes hidden. **Ask your tutor** opens a separate drawer for questions and checking answers. The outline, objectives and references remain accessible; the outline collapses on narrow screens. Your current step, reviewed steps and reflection drafts are saved in this browser. A reviewed step records progress through the notes, not mastery. The tutor receives your first attempt, assessment, references, and recent conversation. Without an assessment, the UI explicitly uses a general curated path. Lesson timing is guidance, not a forced timer.
5. **Explain again.** Notes disappear on the second recording screen. Compare coverage, corrected claims, delivery measurements, transcripts, and both recordings. Rate recall and save the review date.

Sessions resume from the home screen or history. Raw audio is preserved. Processing runs in one background worker to avoid loading several analysis jobs at once; after a server interruption, recordings remain saved and interrupted jobs can be retried. The cold attempt cannot be overwritten after feedback is revealed. Completed sessions preserve their transcripts; retry can still recover missing analysis.

## What works

| Area | Implemented behavior |
| --- | --- |
| Topic catalog | 16 original reference summaries, 68 reference concepts, sources, checks, 8 categories, 3 difficulties, 6 prompt types |
| Recording | Browser MediaRecorder; real input activity; timer; pause/resume; playback; re-record before save; import; local download |
| Storage | SQLite sessions/attempts/messages/reviews; original audio plus decoded analysis WAV; stable UUID filenames |
| Transcription | whisper.cpp adapter; segments where supplied; manual correction; independent retry |
| Technical assessment | Ollama JSON schema; Pydantic validation; exact concept-set and excerpt checks; one repair retry; transparent four-state rubric |
| Audio | Relative loudness, P10–P90 spread, energy-based activity and internal pauses, extended silence, Praat pitch contour and spread |
| Transcript metrics | WPM, limited filler-phrase counts, approximate 30-second speaking-rate windows when timestamps exist |
| Coaching | Clearly labeled tentative suggestions from measurements and transcript evidence; no confidence/emotion scoring |
| Learning | Gap-focused curated sections, reflection fields, optional checks, grounded local conversational tutor with persisted dialogue |
| Comparison | Concept-by-concept before/after, corrected inaccuracies, missing concepts, metric comparison, both audio files and transcripts |
| Retention | Review dates, weighted recommendations, history, previous post-study coverage versus the next cold attempt on a later day |
| UI | Responsive layouts, light/dark mode, labeled controls, keyboard focus, reduced-motion support, meaningful unavailable/loading states |

The 68 concept count includes eight neural-network concepts; other topics have four. Reference content is original concise teaching material with links to supporting documentation, not downloaded at runtime.

## Measurements and rubric

- **Concepts:** correct = accurately demonstrated, partial = incomplete explanation, missing = absent, incorrect = an explicit inaccurate statement. Counts are displayed; there is no invented precision score. A verbatim excerpt proves the words were said, not that the model's interpretation is correct. Scope and audience remain judgment calls.
- **Rate:** transcript word count / recording duration in minutes, including pauses. Segment rates distribute segment word counts across overlapping 30-second windows and are approximate. Manual transcript edits clear segment timing, so segment-rate charts become unavailable.
- **Fillers:** case-insensitive `um`, `uh`, `erm`, `er`, `you know`, `I mean` matches. Context matters; transcription can remove disfluencies. Ambiguous `like` is intentionally excluded. Counts are not a quality grade.
- **Activity and pauses:** 30 ms RMS windows with 10 ms hops; an adaptive energy threshold; short gaps bridged. Internal low-energy gaps ≥0.3s count as pauses. Low-energy runs ≥2s also appear as extended silences, including the recording edges. This is not a learned speech detector: background noise and soft speech affect it.
- **Loudness:** RMS in relative dBFS and active-frame P10–P90 spread. This is not calibrated physical loudness. Microphone placement, room noise, browser processing, and gain confound comparisons.
- **Pitch:** Praat autocorrelation over 60–500 Hz; median and P10–P90 range in semitones. Unvoiced regions are gaps. Out-of-range voices, creak, noise, and octave errors can distort results. Pitch failure leaves other measurements usable.
- **Coaching:** listening exercises and style-dependent suggestions are tentative. Faster, louder, or more variable is never automatically scored as better. Articulation, vocal archetypes, tonality, narrative quality, and audience engagement are not reliably established by these measurements.

Review intervals start at 1 / 2 / 3 / 7 days for again / hard / good / easy. Repeated successful reviews expand the interval, capped at 90 days. Less than 50% fully demonstrated reference concepts caps the rating at again; less than 80% caps easy at hard. This is a deliberately simple heuristic, not a validated mastery estimate. When assessment is unavailable, only your self-rating is used. Retrying analysis after completion does not retroactively reschedule that review. Same-day repeats are not presented as long-term retention.

## Configuration and data

Copy `.env.example` to `.env` at the project root. Configuration is read at backend startup.

| Variable | Default |
| --- | --- |
| `SPEAKLAB_DATA_DIR` | `./data`, relative to the project root |
| `SPEAKLAB_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `SPEAKLAB_OLLAMA_MODEL` | `qwen3.5:9b-q4_K_M` |
| `SPEAKLAB_WHISPER_URL` | `http://127.0.0.1:8080` |
| `SPEAKLAB_OLLAMA_CONTEXT` | `8192` tokens |
| `SPEAKLAB_OLLAMA_MAX_OUTPUT` | `2048` tokens |
| `SPEAKLAB_SERVE_FRONTEND` | `false`; set true after building `frontend/dist` |
| `SPEAKLAB_SERVER_NAME` | `This computer`; the name shown in Settings |
| `SPEAKLAB_MODEL_TIMEOUT` | `180` seconds per model call; one repair call may follow |
| `SPEAKLAB_MAX_UPLOAD_BYTES` | `31457280` (30 MiB) |

The frontend proxy defaults to `http://127.0.0.1:8765`; set `SPEAKLAB_API_TARGET` when launching Vite if you change the backend port. Browser origins are explicitly allowed for local application/test ports. Use `localhost` or `127.0.0.1`, not a LAN IP.

`data/speaklab.sqlite3` contains structured data and `data/recordings/` contains audio. SQLite schema version 3 migrates older versions in place: version 2 added transcription metadata and `analysis_history`; version 3 adds `app_settings` for the selected local model. Newer unknown schema versions fail explicitly. Reanalysis archives the previous public attempt snapshot before updating derived results. Original audio and review dates are preserved; manually edited transcripts cannot be automatically replaced. To back up, stop the backend and copy the entire data directory, including any SQLite sidecar files. Moving a backup to another machine currently requires updating the absolute recording paths in SQLite. Browser-local theme, current lesson step, reviewed steps and reflection drafts live in localStorage; tutor messages submitted successfully are stored in SQLite.

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

Browser tests start dedicated services on 8766 and 5174, use `data/e2e`, and intentionally point model adapters at an unavailable loopback port. They exercise the actual API and DSP, browser recording with Chromium's fake microphone, denial recovery, uploads, manual transcription, lessons, unavailable tutoring, comparison, history, reload persistence, mobile layout, and theme. Synthetic audio and test responses exist only in test/diagnostic code. Browser tests never reuse a running normal server. Test data is separate from practice data.

Backend tests cover structured-output repair, topic-specific concept schemas, transcript evidence selection and resolution, aggregated quote validation errors, invalid excerpts, local-only service configuration, blocked remote Ollama models, transcript invalidation, known-frequency pitch and known-duration pauses, silent audio, upload rejection/cleanup, lesson gating, interrupted jobs, review scheduling, and retention comparison.

OpenAPI is available at `http://127.0.0.1:8765/docs`. Frontend domain contracts live in `frontend/src/types.ts` and the model picker component; incoming requests and model output contracts live in `backend/app/schemas.py`. Runtime logs are JSON events containing route templates and processing identifiers; transcripts and audio are not logged.

```
backend/app/
  main.py          API routes and local request boundary
  db.py            SQLite schema and persistence helpers
  curriculum.py    Safe public catalog, prompts, lessons, recommendations
  topics.json      Curated concepts, examples, checks, and sources
  audio.py         Decode, DSP, transcript metrics, delivery exercises
  models.py        Loopback whisper/Ollama adapters and output validation
  pipeline.py      Durable attempt states and serialized background processing
  progress.py      Review intervals and comparison logic
  schemas.py       Pydantic request and inference contracts
frontend/src/
  App.tsx          Navigation, home, topic library, history, settings
  Recorder.tsx     Browser audio lifecycle and recording workspace
  Practice.tsx     Feedback and comparison
  Learning.tsx     Focused lesson steps, recall, tutor drawer
  Today.tsx        Practice starting point and review summary
  components.tsx   Shared UI and measurement charts
  types.ts         Typed API/domain contracts
scripts/dev.py     Local development launcher
```

## Current limits and next steps

- Real Qwen/Whisper inference has passed a complete synthetic-speech integration run on a Windows/WSL host, including both attempts and tutoring. The original Qwen3/base.en warm-model samples took about 16–18 seconds to process; the newer detailed review adds a model pass and uses small.en. This verifies integration, not assessment accuracy on arbitrary speech. Natural speech, more topics, and standalone Apple Silicon performance still need calibration.
- Technical judgments can be wrong even with valid JSON and genuine excerpts. The curated reference is the baseline; especially for audience-specific prompts, review whether omitted concepts were actually essential.
- The 18-minute lesson is a guided reading, retrieval, and conversation path. It is not a guarantee of 18 minutes of generated content. Initial sections are deterministic curated text selected by gaps; the tutor supplies interactive adaptation when available.
- Pause detection is energy-based, pitch is an estimate, and filler detection is transcript-based. There is no emotion, confidence, charisma, video, or reliable automatic articulation scoring. Vocal archetypes are treated as delivery intentions, not classified identities.
- Review scheduling and longitudinal tracking are a basic foundation. History shows per-session measurements and later cold-attempt recall; advanced trend charts, calibrated mastery, and more adaptive scheduling remain future work.
- Audio is saved to disk when you choose Save. Until then it is held in the browser; closing the page can lose it. The UI warns on normal navigation and provides a download fallback after an upload failure. There is no IndexedDB crash recovery or offline-service-worker installation.
- Browser imports can include video containers, but only the first audio stream is analyzed. No video is recorded or evaluated.
- Single user and one backend process only. Jobs run serially in memory and become retryable after restart. There is no cancellation UI, streaming tutor text, deletion/export interface, or multi-device synchronization. Backups are manual; `scripts/backup-data.sh` provides a verified-archive workflow for a [deployed host](docs/deployment.md#how-to-back-up-and-restore-practice-data).
- Mic behavior has automated Chromium coverage and saved natural desktop-browser recordings; Safari/Firefox still need hands-on verification. Keep consistent mic placement and permissions when comparing recordings.

Useful next work: hands-on speech calibration, unattended Windows reboot verification, scheduled backups, broader topic depth, adaptive study checks, a proper local speech activity detector, accessibility auditing with assistive technology, and retention trends across several weeks of real practice.


## Feedback details

- **Transcripts:** local Whisper receives a disfluent example prompt with non-speech suppression off. The original recognized text is retained. Verbatim-oriented does not mean guaranteed verbatim: omissions and hallucinations remain possible. Estimated token/word timestamps and segment-start fallbacks are labeled. Measured audio pauses appear in the annotated timeline, including pauses inside speech segments, without pretending to know an exact word boundary.
- **Fillers:** um/uh/erm/hmm variants are counted and ranked, with counts per minute and playback links. “Like,” “you know,” “I mean,” “so,” “actually,” “basically,” and “right” are context-dependent candidates and excluded from that total. Exact repeated words are shown separately; intentional emphasis is not automatically penalized.
- **Factual accuracy:** a second bounded local-model pass reviews up to four important claims against curated references. Supported, incorrect, needs qualification, and unverified are distinct. Original evidence and reference text are resolved from constrained IDs; no model-generated source links are accepted. Missing concepts remain separate from false claims. Proposed corrections get a second review by the same model to check for false alarms; this is not independent verification. If that review fails, the claim is marked unverified. A failed extra review does not discard the core assessment. Correct quotations do not guarantee correct interpretation.
- **Vocal foundations:** five practice cards explain rate, relative volume, pitch/melody, pauses, and intended tonality. Fifteen-second audio windows identify passages to replay; pitch is only compared with enough voiced samples. No universal variation targets, emotion detection, facial-expression inference, or charisma scores. Rate windows are estimates; noise, mic gain and automatic processing limit comparisons.
- **Vocabulary:** up to three contextual phrase alternatives include meaning, rationale and practice. Suggestions for claims marked incorrect, qualified or unverified are withheld so factual errors are not reinforced. Review alternatives yourself; an LLM can still propose unnecessary or imperfect wording.
- **Reading level:** optional approximate Flesch–Kincaid US grade band; minimum 100 words and three punctuated sentences. The displayed formula uses heuristic syllable counting on a separate copy with detected hesitations removed. It is not a vocabulary/ability score or a target to maximize. Speech fragments, jargon and ASR punctuation can distort it.
- **Learning paths:** all 16 topics include brief background, per-concept prerequisite bridges, and a concise engineering-practice paragraph with curated source links. Existing section counts are unchanged; no extra lesson per acronym. Content is dated for later review and is available offline.

Open **Reanalyze & previous versions** in feedback or comparison to upgrade an old recording. Retranscription is optional; earlier text and feedback remain accessible there. Processing can take longer because factual/vocabulary review is a separate request. A completed session’s review schedule is not recalculated.

Validation includes explicit test doubles for malformed evidence and model failures, database upgrade and snapshot preservation, synthetic pitch/pause audio, mobile/browser playback and disclosures, and a separate real-inference calibration on a deployed host. Test data is never inserted into practice history.
