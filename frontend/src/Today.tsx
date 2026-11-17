import { ArrowRight, BookOpen, Clock3, Mic, Shuffle } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, dateLabel, errorText } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { HistoryRow, ReadyRow, Topic } from "./types";

const READY_SHOWN = 3;

export function Today({
  selected,
  selectedPractised,
  reason,
  emptyMessage,
  busy,
  history,
  practisedPill,
  onOpen,
  onShuffle,
  navigate,
}: {
  selected: Topic | null;
  selectedPractised: boolean;
  reason: string;
  /** Set when no topic is left to suggest (every match is practised). */
  emptyMessage: string;
  busy: boolean;
  history: HistoryRow[];
  practisedPill: ReactNode;
  onOpen: (topic: Topic) => void;
  onShuffle: () => void;
  navigate: (page: string) => void;
}) {
  const [ready, setReady] = useState<ReadyRow[]>([]);
  const [readyError, setReadyError] = useState("");
  // Due topics come first from the server; the first few keep "Suggested topics" in view.
  const [showAllReady, setShowAllReady] = useState(false);
  const shownReady = showAllReady ? ready : ready.slice(0, READY_SHOWN);
  const loadReady = useCallback(() => {
    setReadyError("");
    api<ReadyRow[]>("/practice/ready")
      .then(setReady)
      .catch((e) => setReadyError(errorText(e)));
  }, []);
  useEffect(() => {
    loadReady();
  }, [loadReady]);
  // History is ordered by the most recent attempt.
  const recent = history[0];
  const attempts = history.reduce((sum, h) => sum + h.attempt_count, 0);
  const topicPath = (id: string) => "topic/" + encodeURIComponent(id);
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
          <p>Explain a concept. Find the gaps. Try again another day.</p>
        </div>
        <span className="time-estimate">
          <Clock3 size={15} /> About 25 minutes
        </span>
      </header>
      {recent && (
        <section
          className="resume-banner"
          aria-label="Pick up where you left off"
        >
          <div>
            <span className="eyebrow">Pick up where you left off</span>
            <strong>{recent.topic.title}</strong>
          </div>
          <button
            className="text-button"
            onClick={() => navigate(topicPath(recent.topic_id))}
          >
            Open topic <ArrowRight size={16} />
          </button>
        </section>
      )}
      {(ready.length > 0 || readyError) && (
        <section
          className="attempt2-list ready-list"
          aria-labelledby="ready-heading"
        >
          <h2 id="ready-heading" className="eyebrow">
            Ready for another attempt
          </h2>
          <ul>
            {shownReady.map((item) => (
              <li key={item.topic_id}>
                <button
                  className="text-button"
                  onClick={() => navigate(topicPath(item.topic_id))}
                >
                  {item.topic.title}
                  <ArrowRight size={14} />
                </button>
                <span className="ready-meta small muted">
                  {item.due && <span className="tag">due</span>}
                  {item.attempt_count}{" "}
                  {item.attempt_count === 1 ? "attempt" : "attempts"} · last{" "}
                  {dateLabel(item.last_attempt_at)}
                </span>
              </li>
            ))}
          </ul>
          {ready.length > READY_SHOWN && (
            <button
              className="text-button muted"
              aria-expanded={showAllReady}
              onClick={() => setShowAllReady((v) => !v)}
            >
              {showAllReady ? "Show fewer" : `Show all (${ready.length})`}
            </button>
          )}
          {readyError && <ErrorNotice message={readyError} retry={loadReady} />}
        </section>
      )}
      <div className="today-grid">
        <section className="topic-hero" aria-label="Suggested topics">
          <div className="hero-top">
            <span className="eyebrow">Suggested topics</span>
            <div className="hero-actions">
              {practisedPill}
              <button
                className="text-button"
                aria-label="Choose another random topic"
                disabled={busy || (!selected && !!emptyMessage)}
                onClick={onShuffle}
              >
                <Shuffle size={15} /> Another topic
              </button>
            </div>
          </div>
          {selected ? (
            <>
              <div className="topic-tags">
                <span>{selected.category}</span>
                <span className="difficulty">{selected.difficulty}</span>
                {selectedPractised && <span className="tag">Practised</span>}
              </div>
              <h2>{selected.title}</h2>
              <p className="hero-prompt">{selected.prompt}</p>
              <div className="hero-footer">
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => onOpen(selected)}
                >
                  {selectedPractised ? (
                    <>
                      Open topic <ArrowRight size={16} />
                    </>
                  ) : (
                    <>
                      <Mic size={17} /> Begin your practice{" "}
                      <ArrowRight size={16} />
                    </>
                  )}
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
          ) : emptyMessage ? (
            <p className="hero-empty">{emptyMessage}</p>
          ) : (
            <Loading />
          )}
        </section>
        <aside className="daily-loop">
          <h2>A topic, in three parts</h2>
          {[
            [
              "01",
              "Explain from memory",
              "Record what you know, without preparation.",
            ],
            [
              "02",
              "Work through the gaps",
              "Read your review and ask the coach about one idea at a time.",
            ],
            [
              "03",
              "Explain it again",
              "On a later day, put the notes away and see what changed.",
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
            <BookOpen size={15} /> Every attempt and its coach chat stay on the
            topic’s page.
          </p>
        </aside>
      </div>
      <div className="home-bottom single">
        <section className="progress-card">
          <span className="eyebrow">Your practice</span>
          <div className="practice-numbers">
            <div>
              <strong>{history.length}</strong>
              <span>topics practised</span>
            </div>
            <div>
              <strong>{attempts}</strong>
              <span>attempts recorded</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
