import { ArrowRight, BookOpen, Clock3, Mic, Shuffle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, dateLabel, errorText, put } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { Attempt2Item, HistoryItem, Review, Topic } from "./types";

export function Today({
  selected,
  reason,
  busy,
  sessions,
  reviews,
  settings,
  onStart,
  onShuffle,
  navigate,
}: {
  selected: Topic | null;
  reason: string;
  busy: boolean;
  sessions: HistoryItem[];
  reviews: Review[];
  settings: ReactNode;
  onStart: (topic?: Topic) => void;
  onShuffle: () => void;
  navigate: (page: string) => void;
}) {
  // A session whose attempt 2 is open is reached through "Record attempt 2": continuing it
  // here would open the full attempt 1 review right before the recall test.
  const today = new Date().toLocaleDateString("en-CA");
  const attempt2Open = (s: HistoryItem) =>
    s.stage === "record2" ||
    (s.stage === "review1" && (!s.attempt2_after || s.attempt2_after <= today));
  const unfinished = sessions.find((s) => !s.completed_at && !attempt2Open(s));
  const complete = sessions.filter((s) => s.completed_at);
  const due = reviews.filter((r) => r.overdue);
  const [queue, setQueue] = useState<Attempt2Item[]>([]);
  const [queueError, setQueueError] = useState("");
  const [loadError, setLoadError] = useState("");
  const loadQueue = useCallback(() => {
    setLoadError("");
    api<Attempt2Item[]>("/attempt2")
      .then(setQueue)
      .catch((e) => setLoadError(errorText(e)));
  }, []);
  useEffect(() => {
    loadQueue();
  }, [loadQueue]);
  async function openAttempt2(id: string) {
    setQueueError("");
    try {
      await put(`/sessions/${id}/stage`, { stage: "record2" });
      navigate(`session/${id}`);
    } catch (e) {
      setQueueError(errorText(e));
    }
  }
  return (
    <div className="today-page">
      <header className="home-heading">
        <div>
          <span className="eyebrow">
            {new Date().toLocaleDateString(undefined, {
              weekday: "long",
              month: "long",
              day: "numeric",
            })}
          </span>
          <h1>Today’s practice</h1>
          <p>Explain a concept. Find the gaps. Try again.</p>
        </div>
        <span className="time-estimate">
          <Clock3 size={15} /> About 25 minutes
        </span>
      </header>
      {unfinished && (
        <div className="resume-banner">
          <div>
            <span className="eyebrow">In progress</span>
            <strong>{unfinished.topic.title}</strong>
          </div>
          <button
            className="text-button"
            onClick={() => navigate(`session/${unfinished.id}`)}
          >
            Continue session <ArrowRight size={16} />
          </button>
        </div>
      )}
      {(queue.length > 0 || loadError) && (
        <section className="attempt2-list" aria-label="Second attempts">
          <span className="eyebrow">Second attempts</span>
          <ul>
            {queue.map((item) => (
              <li key={item.session_id}>
                <strong>{item.topic.title}</strong>
                {item.available ? (
                  <button
                    className="button primary small"
                    onClick={() => void openAttempt2(item.session_id)}
                  >
                    Record attempt 2
                  </button>
                ) : (
                  <span className="small muted">Opens tomorrow</span>
                )}
              </li>
            ))}
          </ul>
          {loadError && <ErrorNotice message={loadError} retry={loadQueue} />}
          {queueError && <ErrorNotice message={queueError} />}
        </section>
      )}
      <div className="today-grid">
        <section className="topic-hero" aria-label="Suggested practice">
          <div className="hero-top">
            <span className="eyebrow">Suggested topic</span>
            <button
              className="text-button"
              aria-label="Choose another random topic"
              disabled={busy}
              onClick={onShuffle}
            >
              <Shuffle size={15} /> Another topic
            </button>
          </div>
          {selected ? (
            <>
              <div className="topic-tags">
                <span>{selected.category}</span>
                <span className="difficulty">{selected.difficulty}</span>
              </div>
              <h2>{selected.title}</h2>
              <p className="hero-prompt">{selected.prompt}</p>
              <div className="hero-footer">
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => onStart()}
                >
                  <Mic size={17} /> Begin your practice <ArrowRight size={16} />
                </button>
                <button
                  className="button ghost"
                  onClick={() => navigate("topics")}
                >
                  Choose a topic
                </button>
              </div>
              <p className="hero-reason">{reason}</p>
            </>
          ) : (
            <Loading />
          )}
          <details className="practice-settings">
            <summary>
              Practice settings <span>Duration, prompt & delivery</span>
            </summary>
            {settings}
          </details>
        </section>
        <aside className="daily-loop">
          <h2>A session, in three parts</h2>
          {[
            [
              "01",
              "Explain from memory",
              "Record what you know, without preparation.",
            ],
            [
              "02",
              "Work through the gaps",
              "Review your explanation and study one idea at a time.",
            ],
            [
              "03",
              "Explain it again",
              "Put the notes away and see what changed.",
            ],
          ].map(([number, title, description]) => (
            <div className="loop-item" key={number}>
              <span>{number}</span>
              <div>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </div>
          ))}
          <p className="loop-note">
            <BookOpen size={15} /> Reviews bring topics back for a fresh
            explanation on another day.
          </p>
        </aside>
      </div>
      <div className="home-bottom">
        <section className="review-card">
          <span className="eyebrow">Review queue</span>
          <h2>
            {due.length
              ? `${due.length} topic${due.length === 1 ? "" : "s"} ready to revisit`
              : "Room to remember"}
          </h2>
          <p>
            {due.length
              ? "Start with a cold explanation to find out what you retained."
              : reviews.length
                ? `Your next review is ${dateLabel(reviews[0].due)}.`
                : "Complete a session to schedule your first review."}
          </p>
          <button
            className="text-button"
            onClick={() =>
              due.length ? onStart(due[0].topic) : navigate("history")
            }
          >
            {due.length ? "Start a memory check" : "View practice history"}
            <ArrowRight size={15} />
          </button>
        </section>
        <section className="progress-card">
          <span className="eyebrow">Your practice</span>
          <div className="practice-numbers">
            <div>
              <strong>{complete.length}</strong>
              <span>sessions completed</span>
            </div>
            <div>
              <strong>{new Set(complete.map((s) => s.topic.id)).size}</strong>
              <span>topics practiced</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
