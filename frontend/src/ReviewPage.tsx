import { useCallback, useState } from "react";
import { PanelLeftOpen, X } from "lucide-react";
import { errorText, post } from "./api";
import { CoachChat } from "./CoachChat";
import { FillerDetails, ReadingLevel, VocalFoundations } from "./Insights";
import { ErrorNotice } from "./components";
import { AcousticPanel, AttemptStatus } from "./Practice";
import { isTooShort, reviewStructure, ReviewTab } from "./ReviewTab";
import { TranscriptEditor, TranscriptTab } from "./TranscriptTab";
import { VocalVariation } from "./VocalVariation";
import type { Attempt, Thread } from "./types";

type Tab = "transcript" | "review" | "measurements";
const TABS: [Tab, string][] = [
  ["transcript", "Transcript"],
  ["review", "Review"],
  ["measurements", "Measurements"],
];
const PHONE = "(max-width: 899px)";

const hasReview = (attempt: Attempt) =>
  !!reviewStructure(attempt) ||
  isTooShort(attempt) ||
  (attempt.note_state === "legacy" && !!attempt.assessment);

function NoteBox({
  attempt,
  onRefresh,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(skip: boolean) {
    setBusy(true);
    setError("");
    try {
      await post(
        `/attempts/${attempt.id}/note`,
        skip ? { skip: true } : { text: text.trim() },
      );
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="note-box" aria-labelledby={`note-${attempt.id}`}>
      <h3 id={`note-${attempt.id}`}>How did that go?</h3>
      <label className="sr-only" htmlFor={`note-text-${attempt.id}`}>
        Your own read of this attempt
      </label>
      <textarea
        id={`note-text-${attempt.id}`}
        rows={3}
        maxLength={2000}
        placeholder="Optional: your own take. The coach responds to it in the review."
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="actions">
        <button
          className="button primary small"
          disabled={busy || !text.trim()}
          onClick={() => void submit(false)}
        >
          Send
        </button>
        <button
          className="button ghost small"
          disabled={busy}
          onClick={() => void submit(true)}
        >
          Skip
        </button>
      </div>
      {error && <ErrorNotice message={error} />}
    </section>
  );
}

/** One attempt of a topic thread: its transcript, review and measurements, and its own chat.
 * Works for any attempt number; the previous attempt is the one numbered just before it. */
export function ReviewPage({
  thread,
  attemptNumber,
  onRefresh,
  onRecordAgain,
}: {
  thread: Thread;
  attemptNumber: number;
  onRefresh: () => Promise<void>;
  /** Offered only when the server allows replacing this (too-short, latest) attempt. */
  onRecordAgain?: () => void;
}) {
  const attempt = thread.attempts.find((a) => a.number === attemptNumber);
  const previous = thread.attempts.find((a) => a.number === attemptNumber - 1);
  const [chosen, setChosen] = useState<Tab | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [highlight, setHighlight] = useState<{ id: string; tick: number }>({
    id: "",
    tick: 0,
  });
  const refresh = onRefresh;
  const onRef = useCallback((lineId: string) => {
    setChosen("transcript");
    setHighlight((h) => ({ id: lineId, tick: h.tick + 1 }));
    if (window.matchMedia(PHONE).matches) setSheetOpen(true);
  }, []);
  if (!attempt) return null;
  const tab: Tab = chosen ?? (hasReview(attempt) ? "review" : "transcript");
  const showNote = attempt.note_state === "pending" && !isTooShort(attempt);
  return (
    <div className={`review-page ${sheetOpen ? "sheet-open" : ""}`}>
      <AttemptStatus attempt={attempt} onRefresh={refresh} />
      <button
        className="button secondary sheet-toggle"
        onClick={() => setSheetOpen(true)}
      >
        <PanelLeftOpen size={16} /> Transcript & review
      </button>
      <div className="review-columns">
        <div className="review-left">
          <div className="sheet-head">
            <strong>{thread.topic.title}</strong>
            <button
              className="icon-button"
              aria-label="Close transcript and review"
              onClick={() => setSheetOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
          <div className="tabs" role="tablist" aria-label="Attempt details">
            {TABS.map(([value, label]) => (
              <button
                key={value}
                id={`tab-${value}`}
                role="tab"
                aria-selected={tab === value}
                aria-controls={`panel-${value}`}
                className={tab === value ? "on" : ""}
                onClick={() => setChosen(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            className="tab-panel"
            role="tabpanel"
            id={`panel-${tab}`}
            aria-labelledby={`tab-${tab}`}
          >
            {tab === "transcript" ? (
              <>
                <TranscriptTab
                  attempt={attempt}
                  highlighted={highlight.id || null}
                  highlightTick={highlight.tick}
                />
                <TranscriptEditor attempt={attempt} onRefresh={refresh} />
              </>
            ) : tab === "review" ? (
              <ReviewTab
                attempt={attempt}
                previous={previous}
                onRef={onRef}
                onRefresh={refresh}
                onRecordAgain={isTooShort(attempt) ? onRecordAgain : undefined}
              />
            ) : (
              <>
                <details className="measurements">
                  <summary>
                    Voice measurements (pace, pitch, volume, pauses)
                  </summary>
                  <VocalVariation attempt={attempt} style={attempt.style} />
                  <AcousticPanel
                    metrics={attempt.acoustics}
                    duration={attempt.duration}
                  />
                </details>
                <FillerDetails attempt={attempt} />
                <VocalFoundations attempt={attempt} />
                <ReadingLevel attempt={attempt} />
              </>
            )}
          </div>
        </div>
        <div className="review-right">
          {showNote && <NoteBox attempt={attempt} onRefresh={refresh} />}
          <CoachChat
            thread={thread}
            attemptNumber={attemptNumber}
            onRef={onRef}
            onRefresh={refresh}
          />
        </div>
      </div>
    </div>
  );
}
