import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  CalendarDays,
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
  X,
} from "lucide-react";
import { api, dateLabel, errorText, post, put } from "./api";
import { Empty, ErrorNotice, Loading } from "./components";
import { ComparisonView, Feedback, processing } from "./Practice";
import { Learning } from "./Learning";
import { Today } from "./Today";
import { Recorder } from "./Recorder";
import { ModelPicker } from "./ModelPicker";
import type {
  Health,
  HistoryItem,
  Review,
  Session,
  Stage,
  Topic,
} from "./types";

const kinds = [
  "Concept explanation",
  "How it works",
  "Compare",
  "Trade-off",
  "Defend a decision",
  "Nontechnical audience",
];
const styles = [
  "Conversational",
  "Thoughtful teacher",
  "Concise interview",
  "Animated storyteller",
];
const steps: [Stage, string][] = [
  ["record1", "Explain"],
  ["feedback", "Reflect"],
  ["learn", "Learn"],
  ["record2", "Try again"],
  ["compare", "Compare"],
];
const route = () => location.hash.replace(/^#\/?/, "") || "today";

export default function App() {
  const [page, setPage] = useState(route);
  const [health, setHealth] = useState<Health | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [sessions, setSessions] = useState<HistoryItem[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [selected, setSelected] = useState<Topic | null>(null);
  const [reason, setReason] = useState(
    "A fresh perspective for your next practice",
  );
  const [category, setCategory] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [duration, setDuration] = useState(120);
  const [style, setStyle] = useState("Conversational");
  const [kind, setKind] = useState("Concept explanation");
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const currentRoute = useRef(page);
  const navigationApproved = useRef(false);
  dirtyRef.current = dirty;
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("speaklab-theme") === "dark";
    } catch {
      return false;
    }
  });
  const [search, setSearch] = useState("");
  const onDirty = useCallback((value: boolean) => setDirty(value), []);
  const sessionId = page.startsWith("session/") ? page.split("/")[1] : null;
  const navigate = useCallback(
    (destination: string) => {
      if (destination === currentRoute.current) return;
      if (
        dirty &&
        !window.confirm(
          "Leave this unsaved recording? Save it or download a copy before leaving.",
        )
      )
        return;
      setError("");
      navigationApproved.current = true;
      location.hash = "/" + destination;
    },
    [dirty],
  );
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
        history.replaceState(null, "", "#/" + currentRoute.current);
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
  const loadDashboard = useCallback(async () => {
    const [a, b] = await Promise.all([
      api<HistoryItem[]>("/sessions"),
      api<Review[]>("/reviews"),
    ]);
    setSessions(a);
    setReviews(b);
  }, []);
  const checkHealth = useCallback(async () => {
    setHealth(await api<Health>("/health"));
  }, []);
  async function chooseRandom(exclude?: string) {
    setBusy(true);
    setError("");
    try {
      const q = new URLSearchParams();
      if (category) q.set("category", category);
      if (difficulty) q.set("difficulty", difficulty);
      if (exclude) q.set("exclude", exclude);
      const r = await api<{ topic: Topic; reason: string }>(
        "/topics/recommend?" + q,
      );
      setSelected(r.topic);
      setReason(r.reason);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let alive = true;
    async function boot() {
      try {
        const [t, r] = await Promise.all([
          api<Topic[]>("/topics"),
          api<{ topic: Topic; reason: string }>("/topics/recommend"),
          loadDashboard(),
        ]);
        if (alive) {
          setTopics(t);
          setSelected(r.topic);
          setReason(r.reason);
        }
        void checkHealth().catch(() => {});
      } catch (e) {
        if (alive) setError(errorText(e));
      } finally {
        if (alive) setBooting(false);
      }
    }
    void boot();
    return () => {
      alive = false;
    };
  }, [loadDashboard, checkHealth]);
  useEffect(() => {
    if (page === "today" || page === "history")
      void loadDashboard().catch((e) => setError(errorText(e)));
  }, [page, loadDashboard]);
  const refreshSession = useCallback(async () => {
    if (sessionId) setSession(await api<Session>(`/sessions/${sessionId}`));
  }, [sessionId]);
  useEffect(() => {
    setSession(null);
    if (sessionId) void refreshSession().catch((e) => setError(errorText(e)));
  }, [sessionId, refreshSession]);
  const running = session?.attempts.some(processing);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(
      () => void refreshSession().catch((e) => setError(errorText(e))),
      2500,
    );
    return () => clearInterval(timer);
  }, [running, refreshSession]);
  async function start(topic = selected) {
    if (!topic) return;
    setBusy(true);
    setError("");
    try {
      const s = await post<Session>("/sessions", {
        topic_id: topic.id,
        duration,
        style,
        prompt_kind: kind,
      });
      navigate(`session/${s.id}`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function changeStage(stage: Stage) {
    if (!session) return;
    setError("");
    try {
      setSession(
        await put<Session>(`/sessions/${session.id}/stage`, { stage }),
      );
      window.scrollTo(0, 0);
    } catch (e) {
      setError(errorText(e));
    }
  }
  const due = reviews.filter((r) => r.overdue);
  const categories = [...new Set(topics.map((t) => t.category))];
  const allLocal = health?.ollama && health.whisper;
  const settingsControls = (
    <div className="practice-options">
      <label>
        Speaking time
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
        >
          <option value={120}>2 minutes</option>
          <option value={180}>3 minutes</option>
          <option value={240}>4 minutes</option>
          <option value={300}>5 minutes</option>
        </select>
      </label>
      <label>
        Prompt style
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {kinds.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </label>
      <label>
        Delivery intention
        <select value={style} onChange={(e) => setStyle(e.target.value)}>
          {styles.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </label>
    </div>
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
                  page === path || (path === "today" && sessionId)
                    ? "active"
                    : ""
                }
                onClick={() => navigate(path as string)}
              >
                <I size={19} />
                <span>
                  {path === "history" ? "History" : (label as string)}
                </span>
                {path === "history" && due.length > 0 && (
                  <span className="nav-count">{due.length}</span>
                )}
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
            {sessionId
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
            sessionId ? "main-content session-content" : "main-content"
          }
        >
          {error && (
            <ErrorNotice
              message={error}
              retry={() => {
                setError("");
                if (sessionId)
                  void refreshSession().catch((e) => setError(errorText(e)));
                else location.reload();
              }}
            />
          )}
          {booting ? (
            <Loading />
          ) : sessionId ? (
            session ? (
              <>
                <div className="session-top">
                  <button
                    className="text-button muted"
                    onClick={() => navigate("today")}
                  >
                    <X size={15} /> Leave practice
                  </button>
                  <span className="small muted">
                    {dateLabel(session.created_at)}
                  </span>
                </div>
                <nav className="stepper" aria-label="Practice stages">
                  {steps.map(([s, label], i) => {
                    const current = steps.findIndex(
                      (v) => v[0] === session.stage,
                    );
                    const enabled =
                      !dirty &&
                      !session.completed_at &&
                      (s === "record1"
                        ? session.stage === "record1"
                        : s === "compare"
                          ? session.attempts.length === 2
                          : session.attempts.length > 0);
                    return (
                      <button
                        className={`${session.stage === s ? "current" : ""} ${i < current ? "done" : ""}`}
                        key={s}
                        disabled={!enabled}
                        onClick={() => void changeStage(s)}
                        aria-current={session.stage === s ? "step" : undefined}
                      >
                        <span>{i < current ? <Check size={13} /> : i + 1}</span>
                        {label}
                      </button>
                    );
                  })}
                </nav>
                {session.stage === "record1" || session.stage === "record2" ? (
                  <Recorder
                    key={session.stage}
                    session={session}
                    number={session.stage === "record1" ? 1 : 2}
                    onSaved={refreshSession}
                    onDirty={onDirty}
                  />
                ) : session.stage === "feedback" ? (
                  <Feedback
                    session={session}
                    onRefresh={refreshSession}
                    onNext={() => void changeStage("learn")}
                  />
                ) : session.stage === "learn" ? (
                  <Learning
                    session={session}
                    onRefresh={refreshSession}
                    onNext={() => void changeStage("record2")}
                  />
                ) : (
                  <ComparisonView
                    session={session}
                    onRefresh={refreshSession}
                    onHome={() => navigate("today")}
                  />
                )}
              </>
            ) : (
              !error && <Loading />
            )
          ) : page === "today" ? (
            <Today
              selected={selected}
              reason={reason}
              busy={busy}
              sessions={sessions}
              reviews={reviews}
              settings={settingsControls}
              onStart={(topic) => void start(topic)}
              onShuffle={() => void chooseRandom(selected?.id)}
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
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void chooseRandom(selected?.id)}
                >
                  <Shuffle size={16} /> Pick for me
                </button>
              </div>
              <div className="topic-library">
                {topics
                  .filter(
                    (t) =>
                      (!category || t.category === category) &&
                      (!difficulty || t.difficulty === difficulty) &&
                      t.title.toLowerCase().includes(search.toLowerCase()),
                  )
                  .map((t) => (
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
                      <span className="difficulty">{t.difficulty}</span>
                    </button>
                  ))}
              </div>
              {!topics.some(
                (t) =>
                  (!category || t.category === category) &&
                  (!difficulty || t.difficulty === difficulty) &&
                  t.title.toLowerCase().includes(search.toLowerCase()),
              ) && (
                <Empty title="Try a broader search">
                  There are no topics matching these filters.
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
                  onClick={() => void start()}
                >
                  Begin practice
                  <ArrowRight size={17} />
                </button>
              </div>
              {settingsControls}
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
                  <CalendarDays size={20} />
                  <h2>Your review queue</h2>
                  <span className="tag">{due.length} ready</span>
                </div>
                {reviews.length ? (
                  <div className="review-list">
                    {reviews.map((r) => (
                      <div key={r.topic_id}>
                        <div>
                          <h3>{r.topic.title}</h3>
                          <p>
                            {r.overdue
                              ? "Ready for a cold explanation"
                              : `Review on ${dateLabel(r.due)}`}{" "}
                            · {r.interval_days} day interval
                          </p>
                        </div>
                        <button
                          className="button secondary small"
                          disabled={busy}
                          onClick={() => void start(r.topic)}
                        >
                          Practice again
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    icon={<CalendarDays size={26} />}
                    title="Give your first idea a place to return."
                  >
                    Finish a practice session to schedule a review. Each review
                    starts from memory.
                  </Empty>
                )}
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <History size={20} />
                  <h2>Previous sessions</h2>
                </div>
                {sessions.length ? (
                  <div className="table-wrap">
                    <table className="history-table">
                      <thead>
                        <tr>
                          <th>Topic / date</th>
                          <th>Concepts demonstrated</th>
                          <th>Speaking rate</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sessions.map((s) => (
                          <tr key={s.id}>
                            <td>
                              <button
                                className="text-button"
                                onClick={() => navigate(`session/${s.id}`)}
                              >
                                {s.topic.title}
                                <ChevronRight size={14} />
                              </button>
                              <small>{dateLabel(s.created_at)}</small>
                            </td>
                            <td>
                              {s.coverage.length
                                ? s.coverage
                                    .map((c) =>
                                      c.correct == null
                                        ? "—"
                                        : `${c.correct}/${c.total}`,
                                    )
                                    .join(" → ")
                                : "—"}
                            </td>
                            <td>
                              {s.coverage.length
                                ? s.coverage
                                    .map((c) => c.wpm ?? "—")
                                    .join(" → ")
                                : "—"}{" "}
                              <span className="muted small">WPM</span>
                            </td>
                            <td>
                              <span
                                className={`tag ${s.completed_at ? "completed" : ""}`}
                              >
                                {s.completed_at ? "Complete" : "In progress"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="muted small">
                      Before → after, within each session. Rate changes have no
                      automatic “better” direction. Compare cold attempts across
                      different days to explore retention.
                    </p>
                  </div>
                ) : (
                  <Empty
                    icon={<Mic size={26} />}
                    title="Every clear explanation starts somewhere."
                  >
                    Your recordings and reflections will live here after you
                    begin your first practice.
                  </Empty>
                )}
              </section>
              <section className="retention-note">
                <CircleHelp size={22} />
                <div>
                  <h3>Immediate improvement is one piece of the story.</h3>
                  <p>
                    After a later review, the comparison screen shows which
                    previously demonstrated concepts appeared in your new cold
                    attempt. Same-day improvement is kept separate from
                    longer-term recall.
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
                    <h2>Technical tutor</h2>
                    <span
                      className={`tag ${health?.ollama ? "completed" : ""}`}
                    >
                      {health?.ollama ? "Ready" : "Unavailable"}
                    </span>
                  </div>
                  <h3>Ollama · {health?.model ?? "qwen3.5:9b-q4_K_M"}</h3>
                  <p>Grounded concept assessment and interactive tutoring.</p>
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
                      feedback, and tutor conversations.
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
