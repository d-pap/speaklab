import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  MessageCircle,
  Send,
  X,
} from "lucide-react";
import { api, errorText, post } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { Lesson, Session } from "./types";

function savedStep(id: string) {
  try {
    return Math.max(
      0,
      Number(localStorage.getItem(`speaklab-lesson-step-${id}`)) || 0,
    );
  } catch {
    return 0;
  }
}

export function Learning({
  session,
  onRefresh,
  onNext,
}: {
  session: Session;
  onRefresh: () => Promise<void>;
  onNext: () => void;
}) {
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [error, setError] = useState("");
  const [index, setIndex] = useState(() => savedStep(session.id));
  const [mode, setMode] = useState<"read" | "recall">("read");
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [reflection, setReflection] = useState("");
  const [busy, setBusy] = useState(false);
  const [chatError, setChatError] = useState("");
  const [reviewed, setReviewed] = useState<string[]>(() => {
    try {
      const value: unknown = JSON.parse(
        localStorage.getItem(`speaklab-lesson-reviewed-${session.id}`) || "[]",
      );
      return Array.isArray(value)
        ? value.filter((v): v is string => typeof v === "string")
        : [];
    } catch {
      return [];
    }
  });
  const drawer = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const assessment = session.attempts[0]?.assessment;
  useEffect(() => {
    let alive = true;
    api<Lesson>(`/sessions/${session.id}/lesson`)
      .then((l) => {
        if (alive) {
          setLesson(l);
          setIndex((i) => Math.min(i, Math.max(0, l.sections.length - 1)));
        }
      })
      .catch((e) => {
        if (alive) setError(errorText(e));
      });
    return () => {
      alive = false;
    };
  }, [session.id, assessment]);
  useEffect(() => {
    try {
      setReflection(
        localStorage.getItem(`speaklab-reflection-${session.id}-${index}`) ??
          "",
      );
    } catch {
      setReflection("");
    }
  }, [session.id, index]);
  useEffect(() => {
    if (conversation.current)
      conversation.current.scrollTop = conversation.current.scrollHeight;
  }, [session.messages, busy]);
  function selectStep(next: number) {
    setIndex(next);
    setMode("read");
    setOutlineOpen(false);
    try {
      localStorage.setItem(`speaklab-lesson-step-${session.id}`, String(next));
    } catch {
      /* Session stays usable without browser storage. */
    }
    heading.current?.focus();
  }
  function markReviewed(title: string) {
    const next = [...new Set([...reviewed, title])];
    setReviewed(next);
    try {
      localStorage.setItem(
        `speaklab-lesson-reviewed-${session.id}`,
        JSON.stringify(next),
      );
    } catch {
      /* Progress remains in memory. */
    }
  }
  async function send(text = message) {
    if (!text.trim() || busy) return;
    setBusy(true);
    setChatError("");
    try {
      await post(`/sessions/${session.id}/tutor`, { message: text });
      setMessage("");
      await onRefresh();
    } catch (e) {
      setChatError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (error) return <ErrorNotice message={error} />;
  if (!lesson) return <Loading label="Preparing your learning path…" />;
  if (!lesson.sections.length)
    return (
      <ErrorNotice message="This lesson has no sections. Return to feedback and try opening it again." />
    );
  const section = lesson.sections[index];
  const count = lesson.sections.length;
  const reviewedCount = lesson.sections.filter((s) =>
    reviewed.includes(s.title),
  ).length;
  return (
    <div className="learning-workspace">
      <header className="learning-heading">
        <div>
          <span className="eyebrow">
            Learning · about {lesson.estimated_minutes} minutes
          </span>
          <h1>{session.topic.title}</h1>
        </div>
        <button className="button secondary small" onClick={onNext}>
          Record your second explanation <ArrowRight size={15} />
        </button>
      </header>
      {!lesson.personalized && (
        <p className="path-note">
          <BookOpen size={16} /> Curated study path. Gap selection becomes
          available when your first assessment finishes.
        </p>
      )}
      <div className="learning-layout">
        <aside className={`learning-outline ${outlineOpen ? "expanded" : ""}`}>
          <button
            className="outline-toggle"
            aria-expanded={outlineOpen}
            aria-controls="lesson-navigation"
            onClick={() => setOutlineOpen((value) => !value)}
          >
            <span>
              Lesson outline{" "}
              <span>
                {index + 1} / {count}
              </span>
            </span>
            <ChevronDown size={16} />
          </button>
          <div className="outline-heading">
            <h2>Your learning path</h2>
            <span>
              {reviewedCount}/{count} reviewed
            </span>
          </div>
          <progress
            value={reviewedCount}
            max={count}
            aria-label="Lesson steps reviewed"
          />
          <nav id="lesson-navigation" aria-label="Lesson sections">
            {lesson.sections.map((s, i) => (
              <button
                key={s.title}
                className={index === i ? "selected" : ""}
                aria-current={index === i ? "step" : undefined}
                onClick={() => selectStep(i)}
              >
                <span
                  className={`outline-number ${reviewed.includes(s.title) ? "reviewed" : ""}`}
                >
                  {reviewed.includes(s.title) ? (
                    <Check size={13} aria-label="Reviewed" />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <span>{s.title}</span>
              </button>
            ))}
          </nav>
          <details className="lesson-resource">
            <summary>Learning objectives</summary>
            <ul>
              {lesson.objectives.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
          </details>
          <details className="lesson-resource">
            <summary>
              References <span>{lesson.sources.length}</span>
            </summary>
            <div>
              {lesson.sources.map((s) => (
                <a href={s.url} target="_blank" rel="noreferrer" key={s.url}>
                  {s.title} ↗
                </a>
              ))}
            </div>
          </details>
        </aside>
        <div className="learning-body">
          <div className="lesson-toolbar">
            <span>
              Step {index + 1} of {count}
              <span aria-hidden="true"> / </span>
              {section.minutes} min
            </span>
            <button
              className="text-button"
              onClick={() => drawer.current?.showModal()}
            >
              <MessageCircle size={16} /> Ask your tutor
              {session.messages.length > 0 && (
                <span className="message-count">
                  {
                    session.messages.filter((m) => m.role === "assistant")
                      .length
                  }
                </span>
              )}
            </button>
          </div>
          <article className="study-sheet" aria-labelledby="lesson-title">
            <div className="study-content">
              <span className="eyebrow">
                {mode === "read"
                  ? "Understand the idea"
                  : "Explain it from memory"}
              </span>
              <h2 id="lesson-title" ref={heading} tabIndex={-1}>
                {section.title}
              </h2>
              {mode === "read" ? (
                <>
                  {section.context && (
                    <div className="study-context">
                      <h3>Context</h3>
                      <p>{section.context}</p>
                    </div>
                  )}
                  <div className="study-explanation">
                    <p>{section.body}</p>
                  </div>
                  {section.practice && (
                    <details className="study-practice">
                      <summary>In engineering practice</summary>
                      <p>{section.practice}</p>
                    </details>
                  )}
                  <button
                    className="button secondary recall-button"
                    onClick={() => {
                      setMode("recall");
                      heading.current?.focus();
                    }}
                  >
                    Check your understanding <ArrowRight size={15} />
                  </button>
                  <p className="check-hint">
                    Optional · explain the idea without looking at the notes.
                  </p>
                </>
              ) : (
                <div className="study-recall">
                  <p className="recall-question">{section.question}</p>
                  <label className="field-label" htmlFor="reflection">
                    Your explanation from memory
                  </label>
                  <textarea
                    id="reflection"
                    rows={5}
                    value={reflection}
                    placeholder="Explain it in your own words…"
                    onChange={(e) => {
                      setReflection(e.target.value);
                      try {
                        localStorage.setItem(
                          `speaklab-reflection-${session.id}-${index}`,
                          e.target.value,
                        );
                      } catch {
                        /* Note stays in memory. */
                      }
                    }}
                  />
                  <div className="recall-actions">
                    <button
                      className="text-button"
                      onClick={() => setMode("read")}
                    >
                      <ArrowLeft size={14} /> Back to the explanation
                    </button>
                    <button
                      className="button secondary small"
                      disabled={!reflection.trim() || busy}
                      onClick={() => {
                        const text = `Please check my understanding of ${section.title}. Question: ${section.question}\nMy answer: ${reflection}`;
                        setMessage(text);
                        drawer.current?.showModal();
                        void send(text);
                      }}
                    >
                      Ask the tutor to check this <ArrowRight size={14} />
                    </button>
                  </div>
                  <span className="draft-note">
                    Draft saved in this browser.
                  </span>
                </div>
              )}
            </div>
            <footer className="study-footer">
              <button
                className="button ghost"
                disabled={index === 0}
                onClick={() => selectStep(index - 1)}
              >
                <ArrowLeft size={16} /> Previous
              </button>
              {index < count - 1 ? (
                <button
                  className="button primary"
                  onClick={() => {
                    markReviewed(section.title);
                    selectStep(index + 1);
                  }}
                >
                  Next idea <ArrowRight size={16} />
                </button>
              ) : (
                <button
                  className="button primary"
                  onClick={() => {
                    markReviewed(section.title);
                    onNext();
                  }}
                >
                  Try explaining it <ArrowRight size={16} />
                </button>
              )}
            </footer>
          </article>
          <p className="learning-footnote">
            A reviewed step records your progress through the notes, not mastery
            of the concept.
          </p>
        </div>
      </div>
      <dialog
        ref={drawer}
        className="tutor-drawer"
        aria-labelledby="tutor-title"
      >
        <header className="tutor-header">
          <div>
            <span className="eyebrow">Local tutor</span>
            <h2 id="tutor-title">Let’s work through it</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close tutor"
            onClick={() => drawer.current?.close()}
          >
            <X size={20} />
          </button>
        </header>
        <p className="tutor-context">
          Current step: <strong>{section.title}</strong>
        </p>
        <div
          className="conversation"
          ref={conversation}
          aria-live="polite"
          aria-busy={busy}
        >
          {session.messages.length ? (
            session.messages.map((m) => (
              <div key={m.id} className={`message ${m.role}`}>
                <span className="eyebrow">
                  {m.role === "user" ? "You" : "Tutor"}
                </span>
                <p className="preserve">{m.content}</p>
              </div>
            ))
          ) : (
            <div className="tutor-empty">
              <p>Need a different explanation?</p>
              <span>
                Ask about a mechanism, request an example, or check your
                understanding.
              </span>
              <button
                className="button secondary"
                onClick={() => {
                  const text = `Walk me through ${section.title} with a concrete example. Begin with any background I need.`;
                  setMessage(text);
                  void send(text);
                }}
              >
                Walk me through an example
              </button>
            </div>
          )}
          {busy && <Loading label="Your local tutor is thinking…" />}
        </div>
        {chatError && (
          <ErrorNotice message={chatError} retry={() => void send()} />
        )}
        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <label className="sr-only" htmlFor="tutor-message">
            Ask your tutor
          </label>
          <textarea
            autoFocus
            id="tutor-message"
            maxLength={2500}
            rows={3}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="What would you like to understand?"
          />
          <button
            className="button primary icon-button"
            aria-label="Send question"
            disabled={busy || !message.trim()}
          >
            <Send size={17} />
          </button>
        </form>
        <p className="tutor-disclaimer">
          Model feedback can be mistaken. Use the lesson references to check
          factual claims.
        </p>
      </dialog>
    </div>
  );
}
