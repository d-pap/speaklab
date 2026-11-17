import { useEffect, useRef, useState } from "react";
import { SendHorizontal } from "lucide-react";
import { ChatNotSent, errorText, streamChat } from "./api";
import { ErrorNotice } from "./components";
import { CoachControls } from "./CoachControls";
import { renderMarkdown } from "./markdown";
import { renderParts, stripMarkersForStreaming } from "./markers";
import { progressLine, reviewing } from "./Practice";
import { isTooShort } from "./ReviewTab";
import { CoachReview } from "./CoachReview";
import { RehearsalRecorder } from "./Recorder";
import { ResponseFeedback } from "./ResponseFeedback";
import type { Message, Thread } from "./types";

export function CoachChat({
  thread,
  attemptNumber,
  onRef,
  onRefresh,
}: {
  thread: Thread;
  attemptNumber: number;
  onRef: (lineId: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [streamed, setStreamed] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [controlBusy, setControlBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  // A reply keeps streaming after the chat unmounts (the backend still stores it), but a
  // finished stream must not touch state or refetch a topic the learner has left.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const attempt = thread.attempts.find((a) => a.number === attemptNumber);
  const messages = thread.messages
    .filter((m) => (m.attempt_number ?? 1) === attemptNumber)
    .sort(
      (a, b) =>
        Number(b.kind === "review") - Number(a.kind === "review") ||
        a.id - b.id,
    );
  const waiting = !!attempt && reviewing(attempt);
  const busy = pending !== null;
  const hasReview = messages.some((m) => m.kind === "review");
  // Follow only the learner's own exchange; opening the page or a review arriving never scrolls.
  useEffect(() => {
    if (pending !== null) end.current?.scrollIntoView?.({ block: "nearest" });
  }, [streamed, pending]);

  async function send(message = draft) {
    const text = message.trim();
    if (!text || busy || controlBusy || waiting || !thread.session_id) return;
    setError("");
    setPending(text);
    setStreamed("");
    setDraft("");
    try {
      await streamChat(thread.session_id, attemptNumber, text, (delta) => {
        if (mounted.current) setStreamed((s) => (s ?? "") + delta);
      });
    } catch (e) {
      if (!mounted.current) return;
      setError(errorText(e));
      // Refused before the stream began: nothing was stored, so give the question back.
      if (e instanceof ChatNotSent) setDraft((d) => d || text);
    }
    if (!mounted.current) return;
    // The question is stored either way, so the thread is the source of truth.
    await onRefresh().catch(() => {});
    if (!mounted.current) return;
    setPending(null);
    setStreamed(null);
  }

  // Coach prose is Markdown (headings, bold, lists); the learner's own words stay as typed.
  const bubble = (m: Message) => {
    const parts = m.parts?.length
      ? m.parts
      : [{ type: "text" as const, text: m.content }];
    const coach = m.role !== "user";
    return (
      <div
        key={m.id}
        className={`message ${coach ? "coach md" : "me"} ${m.kind === "review" ? "review" : ""}`}
      >
        {coach && (
          <div className="message-model small muted">
            {m.kind === "review" ? "Review written by " : "Coach · "}
            {m.model ??
              (m.kind === "review"
                ? attempt?.analysis?.passes?.writer.model
                : null) ??
              "Model not recorded"}
          </div>
        )}
        <div className="message-content">
          {coach && m.kind === "review" && attempt ? (
            <CoachReview attempt={attempt} parts={parts} onRef={onRef} />
          ) : coach ? (
            renderMarkdown(parts, onRef)
          ) : (
            renderParts(parts, onRef)
          )}
        </div>
        {coach && <ResponseFeedback message={m} />}
      </div>
    );
  };
  return (
    <section className="coach-chat" aria-label="Coach chat">
      {attempt && (
        <CoachControls
          attempt={attempt}
          disabled={busy || waiting}
          onBusyChange={setControlBusy}
          onRefresh={onRefresh}
        />
      )}
      <div className="chat-log" aria-live="polite">
        {!hasReview && attempt && (
          <p className="small muted chat-placeholder">
            {waiting
              ? (progressLine(attempt) ??
                "The coach is reviewing your attempt…")
              : isTooShort(attempt)
                ? "There’s no written review for a recording this short."
                : "The written review isn’t available. You can still ask the coach about your attempt."}
          </p>
        )}
        {messages.map(bubble)}
        {pending !== null && (
          <>
            <div className="message me">{pending}</div>
            {!!streamed && (
              <div className="message coach streaming">
                {stripMarkersForStreaming(streamed)}
              </div>
            )}
          </>
        )}
        <div ref={end} />
      </div>
      {thread.study_reference && attempt?.transcript && (
        <details className="study-reference">
          <summary>Worked example and sources</summary>
          <p>{thread.study_reference.example}</p>
          <ul>
            {thread.study_reference.sources.map((source) => (
              <li key={source.url}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
      {hasReview && <RehearsalRecorder />}
      {error && <ErrorNotice message={error} />}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {hasReview && !draft && (
          <div
            className="coach-practice-actions"
            aria-label="Practice with your coach"
          >
            <button
              type="button"
              className="button secondary small"
              disabled={busy || controlBusy || waiting}
              onClick={() =>
                void send(
                  "Teach me the most useful concept to work on from this attempt. Use a small engineering example, then give me one different case to explain back.",
                )
              }
            >
              Learn the concept
            </button>
            <button
              type="button"
              className="button secondary small"
              disabled={busy || controlBusy || waiting}
              onClick={() =>
                void send(
                  "Pick one moment from my attempt for a short delivery rehearsal. Show me two ways to say that idea with a different pause, stress or pace. Give me one thing to listen for when I try both aloud.",
                )
              }
            >
              Rehearse my delivery
            </button>
          </div>
        )}
        <label className="sr-only" htmlFor={`chat-${attemptNumber}`}>
          Message the coach
        </label>
        <textarea
          id={`chat-${attemptNumber}`}
          rows={2}
          maxLength={4000}
          placeholder="Ask about your attempt or the topic…"
          value={draft}
          disabled={busy || controlBusy || waiting}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button
          type="submit"
          className="button primary small"
          aria-label="Send message"
          disabled={busy || controlBusy || waiting || !draft.trim()}
        >
          <SendHorizontal size={16} />
        </button>
      </form>
    </section>
  );
}
