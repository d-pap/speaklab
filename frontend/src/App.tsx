import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Coffee,
  History,
  Layers3,
  LockKeyhole,
  Mic,
  Moon,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Shuffle,
  Sparkles,
  Sun,
  Terminal,
} from "lucide-react";
import { api, ApiError, dateLabel, errorText } from "./api";
import { Empty, ErrorNotice, Loading } from "./components";
import { Today } from "./Today";
import { TopicPage } from "./TopicPage";
import { CoachNotes } from "./CoachNotes";
import { ModelPicker } from "./ModelPicker";
import type { Health, HistoryRow, Recommendation, Topic } from "./types";

const route = () => location.hash.replace(/^#\/?/, "") || "today";
const ALL_PRACTISED =
  "You’ve practised every topic here — include practised to see them all";

/** `topic/<id>`, `topic/<id>?attempt=N` and `topic/<id>/new`. */
function topicRoute(page: string) {
  const [path, query = ""] = page.split("?");
  const parts = path.split("/");
  if (parts[0] !== "topic" || !parts[1]) return null;
  const attempt = Number(new URLSearchParams(query).get("attempt"));
  return {
    id: decodeURIComponent(parts[1]),
    attempt: Number.isInteger(attempt) && attempt > 0 ? attempt : null,
    wantsNew: parts[2] === "new",
  };
}

/** Old `#/session/<id>` links: find the session's topic and replace the link with its page. */
function SessionRedirect({ sessionId }: { sessionId: string }) {
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    api<{ topic_id: string }>(`/sessions/${encodeURIComponent(sessionId)}`)
      .then((s) => {
        if (alive)
          location.replace("#/topic/" + encodeURIComponent(s.topic_id));
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [sessionId]);
  return error ? <ErrorNotice message={error} /> : <Loading />;
}

export default function App() {
  const [page, setPage] = useState(route);
  const [health, setHealth] = useState<Health | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [selected, setSelected] = useState<Topic | null>(null);
  const [reason, setReason] = useState(
    "A fresh perspective for your next practice",
  );
  const [suggestionEmpty, setSuggestionEmpty] = useState("");
  const [includePractised, setIncludePractised] = useState(false);
  const [category, setCategory] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [error, setError] = useState("");
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const dirtyRef = useRef(false);
  const currentRoute = useRef(page);
  const navigationApproved = useRef(false);
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("speaklab-theme") === "dark";
    } catch {
      return false;
    }
  });
  const [search, setSearch] = useState("");
  // Read synchronously, so a save that navigates right away isn't stopped by a stale warning.
  const onDirty = useCallback((value: boolean) => {
    dirtyRef.current = value;
  }, []);
  const topicPage = topicRoute(page);
  const sessionId = page.startsWith("session/") ? page.split("/")[1] : null;
  const inPractice = !!topicPage || !!sessionId;
  const navigate = useCallback((destination: string) => {
    if (destination === currentRoute.current) return;
    if (
      dirtyRef.current &&
      !window.confirm(
        "Leave this unsaved recording? Save it or download a copy before leaving.",
      )
    )
      return;
    setError("");
    navigationApproved.current = true;
    location.hash = "/" + destination;
  }, []);
  useEffect(() => {
    const update = () => {
      const next = route();
      if (
        dirtyRef.current &&
        !navigationApproved.current &&
        !window.confirm(
          "Leave this unsaved recording? Save it or download a copy before leaving.",
        )
      ) {
        window.history.replaceState(null, "", "#/" + currentRoute.current);
        return;
      }
      navigationApproved.current = false;
      currentRoute.current = next;
      setPage(next);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("speaklab-theme", dark ? "dark" : "light");
    } catch {
      /* Preference stays in memory. */
    }
  }, [dark]);
  const loadHistory = useCallback(async () => {
    setHistory(await api<HistoryRow[]>("/history"));
  }, []);
  const checkHealth = useCallback(async () => {
    setHealth(await api<Health>("/health"));
  }, []);
  useEffect(() => {
    const refresh = () => void checkHealth().catch(() => {});
    window.addEventListener("speaklab-model-changed", refresh);
    return () => window.removeEventListener("speaklab-model-changed", refresh);
  }, [checkHealth]);
  const practised = new Set(history.map((h) => h.topic_id));
  /** A suggestion from the unpractised topics, or from all of them when practised ones are
   * included. When none is left, a calm empty state rather than an error. */
  const suggest = useCallback(
    async (include: boolean, exclude?: string) => {
      setBusy(true);
      setError("");
      try {
        const q = new URLSearchParams();
        if (category) q.set("category", category);
        if (difficulty) q.set("difficulty", difficulty);
        if (exclude) q.set("exclude", exclude);
        q.set("include_practised", String(include));
        const r = await api<Recommendation>("/topics/recommend?" + q);
        setSelected(r.topic);
        setReason(r.reason);
        setSuggestionEmpty("");
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          setSelected(null);
          setSuggestionEmpty(include ? e.message : ALL_PRACTISED);
        } else setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [category, difficulty],
  );
  // On Today the pill changes the suggestion; in the library it only filters the tiles, so a
  // topic the learner picked stays picked.
  function choosePractised(include: boolean) {
    setIncludePractised(include);
    if (page === "today") void suggest(include);
  }
  useEffect(() => {
    let alive = true;
    async function boot() {
      try {
        const [t] = await Promise.all([api<Topic[]>("/topics"), loadHistory()]);
        if (alive) setTopics(t);
        void checkHealth().catch(() => {});
      } catch (e) {
        if (alive) setError(errorText(e));
      } finally {
        if (alive) setBooting(false);
      }
    }
    void boot();
    void suggest(false);
    return () => {
      alive = false;
    };
    // The first suggestion is made once, at start; later ones follow the learner's choices.
  }, [loadHistory, checkHealth]);
  useEffect(() => {
    if (page === "today" || page === "history" || page === "topics")
      void loadHistory().catch((e) => setError(errorText(e)));
  }, [page, loadHistory]);
  // A suggestion that has since been practised (recorded just now) gives way to a fresh one,
  // so "Suggested topics" stays unpractised unless practised topics are included.
  const stale =
    page === "today" &&
    !includePractised &&
    !!selected &&
    history.some((h) => h.topic_id === selected.id);
  useEffect(() => {
    if (stale) void suggest(false);
  }, [stale, suggest]);
  // A practised topic opens its page; an unpractised one opens on its recording screen.
  const open = (topic: Topic) =>
    navigate("topic/" + encodeURIComponent(topic.id));
  const categories = [...new Set(topics.map((t) => t.category))];
  const allLocal = health?.ollama && health.whisper;
  const shown = topics.filter(
    (t) =>
      (includePractised || !practised.has(t.id)) &&
      (!category || t.category === category) &&
      (!difficulty || t.difficulty === difficulty) &&
      t.title.toLowerCase().includes(search.toLowerCase()),
  );
  const practisedPill = (
    <button
      className="pill-toggle"
      aria-pressed={includePractised}
      onClick={() => choosePractised(!includePractised)}
    >
      {includePractised && <Check size={13} />} Include practised
    </button>
  );
  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#/today"
          onClick={(e) => {
            e.preventDefault();
            navigate("today");
          }}
        >
          <span className="brand-icon">
            <AudioLines size={23} />
          </span>
          SpeakLab
        </a>
        <div className="sidebar-section-label">Workspace</div>
        <nav className="main-nav" aria-label="Main navigation">
          {[
            ["today", "Today", Coffee],
            ["topics", "Topic library", Layers3],
            ["history", "Practice history", History],
          ].map(([path, label, Icon]) => {
            const I = Icon as typeof Coffee;
            return (
              <button
                key={path as string}
                aria-label={label as string}
                className={
                  page === path || (path === "today" && inPractice)
                    ? "active"
                    : ""
                }
                onClick={() => navigate(path as string)}
              >
                <I size={19} />
                <span>
                  {path === "history" ? "History" : (label as string)}
                </span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <button
            aria-label="Settings & local models"
            className={`settings-nav ${page === "settings" ? "active" : ""}`}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={18} />
            <span>Settings</span>
          </button>
          <div className="sidebar-user">
            <span className="user-avatar">D</span>
            <div>
              <strong>Personal workspace</strong>
              <span>Local storage</span>
            </div>
            <button
              className="theme-button"
              aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
              onClick={() => setDark((v) => !v)}
            >
              {dark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            {inPractice
              ? "Your practice workspace"
              : page === "settings"
                ? "Settings"
                : page === "history"
                  ? "History"
                  : "Practice"}
          </span>
          <button className="local-status" onClick={() => navigate("settings")}>
            <span className={`status-dot ${allLocal ? "green" : ""}`} />
            {health
              ? allLocal
                ? "Local models ready"
                : "Local workspace"
              : "On your device"}
            <ChevronRight size={13} />
          </button>
        </header>
        <main
          id="main"
          tabIndex={-1}
          className={
            inPractice ? "main-content session-content" : "main-content"
          }
        >
          {error && (
            <ErrorNotice
              message={error}
              retry={() => {
                setError("");
                location.reload();
              }}
            />
          )}
          {booting ? (
            <Loading />
          ) : topicPage ? (
            <TopicPage
              key={topicPage.id}
              topicId={topicPage.id}
              attemptNumber={topicPage.attempt}
              wantsNew={topicPage.wantsNew}
              navigate={navigate}
              onDirty={onDirty}
            />
          ) : sessionId ? (
            <SessionRedirect key={sessionId} sessionId={sessionId} />
          ) : page === "today" ? (
            <Today
              selected={selected}
              selectedPractised={!!selected && practised.has(selected.id)}
              reason={reason}
              emptyMessage={suggestionEmpty}
              busy={busy}
              history={history}
              practisedPill={practisedPill}
              onOpen={open}
              onShuffle={() => void suggest(includePractised, selected?.id)}
              navigate={navigate}
            />
          ) : page === "topics" ? (
            <div className="stack">
              <div className="page-heading">
                <span className="eyebrow">THE TOPIC LIBRARY</span>
                <h1>Topic library</h1>
                <p>
                  Choose a topic for your next explanation. References stay
                  hidden until after your first attempt.
                </p>
              </div>
              <div className="filters">
                <label>
                  <span className="sr-only">Search topics</span>
                  <input
                    placeholder="Find a topic…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <label>
                  <span className="sr-only">Topic category</span>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="">All categories</option>
                    {categories.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="sr-only">Topic difficulty</span>
                  <select
                    value={difficulty}
                    onChange={(e) => setDifficulty(e.target.value)}
                  >
                    <option value="">All levels</option>
                    {["beginner", "intermediate", "advanced"].map((d) => (
                      <option key={d}>{d}</option>
                    ))}
                  </select>
                </label>
                {practisedPill}
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void suggest(includePractised, selected?.id)}
                >
                  <Shuffle size={16} /> Pick for me
                </button>
              </div>
              {suggestionEmpty && !selected && (
                <p className="muted small">{suggestionEmpty}</p>
              )}
              <div className="topic-library">
                {shown.map((t) => (
                  <button
                    key={t.id}
                    className={`topic-tile ${selected?.id === t.id ? "selected" : ""}`}
                    onClick={() => {
                      setSelected(t);
                      setReason("Chosen by you");
                    }}
                    aria-pressed={selected?.id === t.id}
                  >
                    <div>
                      <span className="eyebrow">{t.category}</span>
                      {selected?.id === t.id ? (
                        <Check size={18} />
                      ) : (
                        <BookOpen size={18} />
                      )}
                    </div>
                    <h3>{t.title}</h3>
                    <p>{t.prompt}</p>
                    <span className="tag-row">
                      <span className="difficulty">{t.difficulty}</span>
                      {practised.has(t.id) && (
                        <span className="tag">Practised</span>
                      )}
                    </span>
                  </button>
                ))}
              </div>
              {!shown.length && (
                <Empty title="Try a broader search">
                  {includePractised || !practised.size
                    ? "There are no topics matching these filters."
                    : "There are no unpractised topics matching these filters. Include practised topics to see them all."}
                </Empty>
              )}
              <div className="selection-bar">
                <div>
                  <span className="eyebrow">YOUR NEXT EXPLANATION</span>
                  <h3>{selected?.title ?? "Choose a topic"}</h3>
                </div>
                <button
                  className="button primary"
                  disabled={!selected || busy}
                  onClick={() => selected && open(selected)}
                >
                  {selected && practised.has(selected.id)
                    ? "Open topic"
                    : "Begin practice"}
                  <ArrowRight size={17} />
                </button>
              </div>
            </div>
          ) : page === "history" ? (
            <div className="stack">
              <div className="page-heading">
                <span className="eyebrow">YOUR PRACTICE HISTORY</span>
                <h1>Understanding takes a little time.</h1>
                <p>
                  Revisit an idea. Hear your progress. Remember what matters.
                </p>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <History size={20} />
                  <h2>Your topics</h2>
                </div>
                {history.length ? (
                  <div className="table-wrap">
                    <table className="history-table">
                      <thead>
                        <tr>
                          <th>Topic / last practised</th>
                          <th>Attempts</th>
                          <th>Concepts demonstrated</th>
                          <th>Speaking rate</th>
                          <th>Next attempt</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((h) => (
                          <tr key={h.topic_id}>
                            <td>
                              <button
                                className="text-button"
                                onClick={() =>
                                  navigate(
                                    "topic/" + encodeURIComponent(h.topic_id),
                                  )
                                }
                              >
                                {h.topic.title}
                                <ChevronRight size={14} />
                              </button>
                              <small>{dateLabel(h.last_attempt_at)}</small>
                            </td>
                            <td>
                              {h.attempt_count}{" "}
                              {h.attempt_count === 1 ? "attempt" : "attempts"}
                            </td>
                            <td>
                              {h.coverage.correct == null
                                ? "—"
                                : `${h.coverage.correct}/${h.coverage.total}`}
                            </td>
                            <td>
                              {h.coverage.wpm ?? "—"}{" "}
                              <span className="muted small">WPM</span>
                            </td>
                            <td>
                              <span
                                className={`tag ${h.can_record ? "completed" : ""}`}
                              >
                                {h.can_record
                                  ? "New attempt open"
                                  : "Next attempt opens tomorrow"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="muted small">
                      Concepts and rate are from each topic’s latest attempt.
                      Rate changes have no automatic “better” direction.
                    </p>
                  </div>
                ) : (
                  <Empty
                    icon={<Mic size={26} />}
                    title="Every clear explanation starts somewhere."
                  >
                    Your topics will live here after your first recording.
                  </Empty>
                )}
              </section>
              <section className="retention-note">
                <CircleHelp size={22} />
                <div>
                  <h3>Immediate improvement is one piece of the story.</h3>
                  <p>
                    Each new attempt comes on a later day, so its review shows
                    what you remembered, not what you just read.
                  </p>
                </div>
              </section>
            </div>
          ) : page === "settings" ? (
            <div className="stack">
              <div className="page-heading">
                <span className="eyebrow">SETTINGS & LOCAL MODELS</span>
                <h1>Settings</h1>
                <p>Manage your local models, storage, and appearance.</p>
              </div>
              <div className="privacy-banner">
                <ShieldCheck size={26} />
                <div>
                  <h3>Everything runs on your connected computer.</h3>
                  <p>
                    Recordings, transcripts, and AI processing stay on the
                    connected computer shown below. After model downloads,
                    practice works without cloud AI. Keep your connection to
                    that computer available when using it remotely.
                  </p>
                </div>
              </div>
              <div className="feedback-grid">
                <section className="panel model-card">
                  <div className="panel-heading">
                    <Sparkles size={20} />
                    <h2>Coach</h2>
                    <span
                      className={`tag ${health?.ollama ? "completed" : ""}`}
                    >
                      {health?.ollama ? "Ready" : "Unavailable"}
                    </span>
                  </div>
                  <h3>Ollama · {health?.model ?? "qwen3.5:9b-q4_K_M"}</h3>
                  <p>
                    Reviews each attempt and answers your questions in the coach
                    chat.
                  </p>
                  <ModelPicker
                    onSaved={(model) => {
                      setHealth((h) => (h ? { ...h, model } : h));
                      void checkHealth().catch(() => {});
                    }}
                  />
                  <span className="small mono muted">
                    {health?.ollama_url ?? "http://127.0.0.1:11434"}
                  </span>
                </section>
                <section className="panel model-card">
                  <div className="panel-heading">
                    <Mic size={20} />
                    <h2>Speech to text</h2>
                    <span
                      className={`tag ${health?.whisper ? "completed" : ""}`}
                    >
                      {health?.whisper ? "Service reachable" : "Unavailable"}
                    </span>
                  </div>
                  <h3>whisper.cpp · base.en or small.en</h3>
                  <p>Local transcription with segment timestamps.</p>
                  <code>
                    whisper-server -m models/ggml-small.en.bin
                    <br /> --host 127.0.0.1 --port 8080
                  </code>
                  <p className="small muted">
                    See the README for building whisper.cpp with Metal and
                    downloading a model. Fillers may be omitted by
                    transcription. You can always correct a transcript manually.
                  </p>
                  <span className="small mono muted">
                    {health?.whisper_url ?? "http://127.0.0.1:8080"}
                  </span>
                </section>
              </div>
              <CoachNotes />
              <section className="panel">
                <h2>Coaching feedback</h2>
                <p>
                  Rate reviews and coach replies with the thumbs below each
                  response. Add details to explain what helped or what you
                  wanted instead.
                </p>
                <p className="small muted">
                  Feedback stays on your connected computer. It collects
                  examples for improving coaching; votes don’t automatically
                  retrain or change your model.
                </p>
                <a
                  className="button secondary small"
                  href="/api/feedback/export"
                  download="speaklab-feedback.json"
                >
                  Export feedback
                </a>
              </section>
              <button
                className="button secondary self-start"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void checkHealth()
                    .catch((e) => setError(errorText(e)))
                    .finally(() => setBusy(false));
                }}
              >
                <RefreshCw size={16} className={busy ? "spin" : ""} /> Check
                local services
              </button>
              <section className="panel">
                <div className="panel-heading">
                  <LockKeyhole size={20} />
                  <h2>Storage & measurement</h2>
                </div>
                <dl className="settings-list">
                  <div>
                    <dt>Connected computer</dt>
                    <dd>{health?.server_name ?? "This computer"}</dd>
                    <dt>Your data folder</dt>
                    <dd>
                      <code>{health?.data_dir ?? "speaklab/data"}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Saved on disk</dt>
                    <dd>
                      Original audio, decoded WAV, SQLite sessions, transcripts,
                      reviews, coach notes and coach chats.
                    </dd>
                  </div>
                  <div>
                    <dt>Audio measurements</dt>
                    <dd>
                      Local NumPy energy analysis and Praat pitch estimation. No
                      emotion or confidence detection.
                    </dd>
                  </div>
                  <div>
                    <dt>When models are offline</dt>
                    <dd>
                      Record, replay, study curated references, compare audio,
                      and schedule reviews. Retry missing analysis whenever your
                      services are ready.
                    </dd>
                  </div>
                  <div>
                    <dt>Appearance</dt>
                    <dd>
                      <button
                        className="button secondary small"
                        onClick={() => setDark((v) => !v)}
                      >
                        {dark ? <Sun size={15} /> : <Moon size={15} />}Use{" "}
                        {dark ? "light" : "dark"} mode
                      </button>
                    </dd>
                  </div>
                </dl>
              </section>
              <div className="gentle-note">
                <Terminal size={19} />
                <span>
                  Setup commands, configuration, tests, and known limitations
                  are in the project README. Restart the backend after changing
                  .env.
                </span>
              </div>
            </div>
          ) : (
            <Empty title="That page isn’t here.">
              <button className="text-button" onClick={() => navigate("today")}>
                Return to your practice
              </button>
            </Empty>
          )}
        </main>
      </div>
    </div>
  );
}
