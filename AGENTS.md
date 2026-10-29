# SpeakLab development

If `.local/AGENTS.local.md` exists, read it first: it holds gitignored, machine-specific notes for a particular deployment and overrides nothing below.

## Project layout and checks

- Python package is installed editable from `backend`. Read `README.md` for the product workflow and `docs/deployment.md` for the optional Windows/WSL host setup.
- Run `.venv/bin/python -m pytest backend/tests -q`, `.venv/bin/ruff check backend`, and `npm --prefix frontend run build` from the root.
- Browser tests use dedicated ports 8766/5174 and `data/e2e`. Never aim them at normal practice data.
- The real-inference harness `scripts/smoke-inference.py` accepts two audio files and a report path. It creates a temporary database and uses actual loopback models. Its synthetic results are not user practice history.
- Never commit machine-specific values (hostnames, IP addresses, usernames, absolute home paths, tailnet names). Read them from environment variables or `.local/`, which is gitignored.

## Deployment

- A deployed host runs a dedicated WSL distro `SpeakLab`: source `/opt/speaklab`, practice data `/var/lib/speaklab`, config `/opt/speaklab/.env`. Keep secrets, recordings, `.venv`, `node_modules`, `.local`, and local data out of source transfer archives.
- Leave other WSL distros (for example Docker Desktop's) intact. Never use `wsl --shutdown` as a routine SpeakLab operation; use `wsl --terminate SpeakLab` only for an intentional recovery test.
- `wsl -d SpeakLab -u speaklab --cd /opt/speaklab --exec /opt/speaklab/.venv/bin/python ...` runs the app's Python commands. `runuser` is not on WSL's direct `--exec` PATH.
- Systemd starts the app, Ollama, and Whisper; a Windows startup task holds the distro open. The app serves the built frontend when `SPEAKLAB_SERVE_FRONTEND=true`. Rebuild on source changes and transfer `frontend/dist`; no Node process is needed on the server.
- Keep app and model listeners on loopback. Local development uses 5173; client tunnel port 4173 is reserved for a remote host.
- `scripts/connect-pc.command` wraps the standard-library `pc_connection.py` supervisor. It reads `SPEAKLAB_PC_*` settings from the environment or `.local/pc.env`, retries dropped SSH, pins the host key from `.local/ssh_known_hosts`, and uses an exclusive lock to prevent duplicate tunnels. Host-key/authentication failures stop for inspection. `--install` manages the macOS launch agent `dev.speaklab.pc-tunnel`; `--status`, `--stop`, `--uninstall` manage it. Tests: `/usr/bin/python3 -m unittest discover -s scripts/tests -v` (explicit SSH process doubles, no models).
- Optional private HTTPS uses Tailscale Serve (port 443 → app 8765, 8443 → Open WebUI 3000). Never use Funnel. `security.py` preserves exact origin/host and client-header checks; extra HTTPS origins come from the validated `SPEAKLAB_BROWSER_ORIGINS` JSON array, with no wildcard allowances. Keep `/opt/speaklab/.env` owned by `speaklab:speaklab`, mode 600.
- Optional Open WebUI is isolated under `/opt/open-webui`, data `/var/lib/open-webui`, systemd `open-webui`, config `/etc/open-webui.env`. It uses the existing Ollama with Tailscale trusted-header SSO and no password signup. Keep its listener on loopback; direct header-less sign-in must fail. Its chat data needs a separate backup from SpeakLab practice data.

## Inference constraints

- The default is Qwen3.5 9B Q4_K_M; Settings can choose another installed local chat model. Keep 8192 context, 2048 output, one loaded model and one request at a time. Whisper small.en runs on CPU; the target GPU has 8 GB VRAM.
- Keep dense pitch/loudness plot arrays out of the model prompt. The stored arrays remain available to the UI.
- Supply the JSON schema in the prompt as well as the Ollama format field, constrain concept IDs to the selected topic, and report all evidence errors in one repair request. Inference selects evidence IDs from bounded transcript excerpts; the app resolves these IDs to original text before validating and storing the assessment. Communication cannot cite an empty excerpt or session settings. Keep ASR line wraps inside complete claims; whitespace-only vocabulary matches resolve back to original characters. Do not accept paraphrases as transcript evidence or silently substitute reference text.
- Tests use explicit model doubles; only the optional smoke harness establishes real inference. A valid quote does not establish that its interpretation is correct.

## Feedback and reanalysis

- SQLite version 3 stores `app_settings.ollama_model`; the picker overrides the initial environment default, persists across startup, and rejects changes while analysis or tutoring is active. `/api/models` inspects installed models; `PUT /api/settings/model` validates and saves a choice.
- Previous public attempt snapshots are archived in `analysis_history`. Use `/api/attempts/{id}/reanalyze` to upgrade saved attempts; preserve manually edited text and completed review schedules. Do not silently overwrite earlier feedback.
- `speech.py` computes hesitation candidates, conservative timestamps, experimental readability and vocal-practice markers. Context-dependent words are not counted as definite hesitations.
- Factual/vocabulary review runs separately through `models.review_insights`. Proposed corrections receive a second bounded review by the same model and become unverified if that check fails. It must use valid excerpt/reference IDs; never polish wording of a claim the review flags as false or unverified.
- Every catalog topic needs background, a bridge for each concept, practice context and curated sources. Keep the original lesson section count.

## Interface

- `Today.tsx` owns the practice home; `Learning.tsx` owns the section reader, optional recall view and native-dialog tutor drawer. The shared visual tokens in `styles.css` are neutral grays in both themes until a palette is chosen.
- Lesson position, reviewed sections and reflection drafts are browser-local. Reviewed means the user advanced through a section, not demonstrated mastery. Keep references hidden during both recording screens.
- Frontend-only server updates need no service restart: back up the previous frontend, transfer new hashed assets first, then replace `frontend/dist/index.html` atomically. Keep old hashed assets available for already-open tabs. Do not overwrite the server's `.env` or practice data.
- `VocalVariation.tsx` presents one foundation at a time using stored metrics; `vocalMetrics.ts` derives comparable full-window ranges without rewriting attempts. Rate uses 30-second transcript windows; pitch/loudness use full 15-second `delivery_windows`. Never label low spread as quietness, monotone delivery or failure. Playback markers wait for audio metadata; keep the range-aware audio fixture in the browser tests.
