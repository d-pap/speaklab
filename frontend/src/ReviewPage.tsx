import { useCallback, useState } from "react";
import { PanelLeftOpen, X } from "lucide-react";
import { api, errorText, post, put } from "./api";
import { CoachChat } from "./CoachChat";
import { FillerDetails, ReadingLevel, VocalFoundations } from "./Insights";
import { ErrorNotice } from "./components";
import { AcousticPanel, AttemptStatus } from "./Practice";
import { isTooShort, reviewStructure, ReviewTab } from "./ReviewTab";
import { TranscriptEditor, TranscriptTab } from "./TranscriptTab";
import { VocalVariation } from "./VocalVariation";
import type { Attempt, Session } from "./types";

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

export function ReviewPage({
  session,
  attemptNumber,
  onSession,
}: {
  session: Session;
  attemptNumber: 1 | 2;
  onSession: (s: Session) => void;
}) {
  const attempt = session.attempts.find((a) => a.number === attemptNumber);
  const previous =
    attemptNumber === 2
      ? session.attempts.find((a) => a.number === 1)
      : undefined;
  const [chosen, setChosen] = useState<Tab | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [stageError, setStageError] = useState("");
  const [highlight, setHighlight] = useState<{ id: string; tick: number }>({
    id: "",
    tick: 0,
  });
  const refresh = useCallback(async () => {
    onSession(await api<Session>(`/sessions/${session.id}`));
  }, [onSession, session.id]);
  const onRef = useCallback((lineId: string) => {
    setChosen("transcript");
    setHighlight((h) => ({ id: lineId, tick: h.tick + 1 }));
    if (window.matchMedia(PHONE).matches) setSheetOpen(true);
  }, []);
  if (!attempt) return null;
  const tab: Tab = chosen ?? (hasReview(attempt) ? "review" : "transcript");
  const locked = !!session.completed_at;
  // Only a too-short attempt 1 may be recorded again; the backend enforces the same rule.
  const canRecordAgain =
    attemptNumber === 1 &&
    session.stage === "review1" &&
    !locked &&
    isTooShort(attempt);
  async function recordAgain() {
    setStageError("");
    try {
      onSession(
        await put<Session>(`/sessions/${session.id}/stage`, {
          stage: "record1",
        }),
      );
    } catch (e) {
      setStageError(errorText(e));
    }
  }
  const showNote =
    attempt.note_state === "pending" && !isTooShort(attempt) && !locked;
  return (
    <div className={`review-page ${sheetOpen ? "sheet-open" : ""}`}>
      <div className="review-heading">
        <span className="eyebrow">Attempt {attemptNumber} · Review</span>
        <h1>{session.topic.title}</h1>
      </div>
      <AttemptStatus attempt={attempt} onRefresh={refresh} />
      {stageError && <ErrorNotice message={stageError} />}
      <button
        className="button secondary sheet-toggle"
        onClick={() => setSheetOpen(true)}
      >
        <PanelLeftOpen size={16} /> Transcript & review
      </button>
      <div className="review-columns">
        <div className="review-left">
          <div className="sheet-head">
            <strong>{session.topic.title}</strong>
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
                {!locked && (
                  <TranscriptEditor attempt={attempt} onRefresh={refresh} />
                )}
              </>
            ) : tab === "review" ? (
              <ReviewTab
                attempt={attempt}
                previous={previous}
                onRef={onRef}
                onRefresh={refresh}
                onRecordAgain={
                  canRecordAgain ? () => void recordAgain() : undefined
                }
              />
            ) : (
              <>
                <details className="measurements">
                  <summary>
                    Voice measurements (pace, pitch, volume, pauses)
                  </summary>
                  <VocalVariation attempt={attempt} style={session.style} />
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
            session={session}
            attemptNumber={attemptNumber}
            onRef={onRef}
            onRefresh={refresh}
          />
        </div>
      </div>
    </div>
  );
}
