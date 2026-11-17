import { useEffect, useRef, useState } from "react";
import { SendHorizontal } from "lucide-react";
import { ChatNotSent, errorText, streamChat } from "./api";
import { ErrorNotice } from "./components";
import { renderMarkdown } from "./markdown";
import { renderParts, stripMarkersForStreaming } from "./markers";
import { progressLine, reviewing } from "./Practice";
import { isTooShort } from "./ReviewTab";
import type { Message, Session } from "./types";

export function CoachChat({
  session,
  attemptNumber,
  onRef,
  onRefresh,
}: {
  session: Session;
  attemptNumber: 1 | 2;
  onRef: (lineId: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [streamed, setStreamed] = useState<string | null>(null);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  // A reply keeps streaming after the chat unmounts (the backend still stores it), but a
  // finished stream must not touch state or refetch a session the learner has left.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const attempt = session.attempts.find((a) => a.number === attemptNumber);
  const messages = session.messages
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

  async function send() {
    const text = draft.trim();
    if (!text || busy || waiting) return;
    setError("");
    setPending(text);
    setStreamed("");
    setDraft("");
    try {
      await streamChat(session.id, attemptNumber, text, (delta) => {
        if (mounted.current) setStreamed((s) => (s ?? "") + delta);
      });
    } catch (e) {
      if (!mounted.current) return;
      setError(errorText(e));
      // Refused before the stream began: nothing was stored, so give the question back.
      if (e instanceof ChatNotSent) setDraft((d) => d || text);
    }
    if (!mounted.current) return;
    // The question is stored either way, so the session is the source of truth.
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
        {coach ? renderMarkdown(parts, onRef) : renderParts(parts, onRef)}
      </div>
    );
  };
  return (
    <section className="coach-chat" aria-label="Coach chat">
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
      {error && <ErrorNotice message={error} />}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label className="sr-only" htmlFor={`chat-${attemptNumber}`}>
          Message the coach
        </label>
        <textarea
          id={`chat-${attemptNumber}`}
          rows={2}
          maxLength={4000}
          placeholder="Ask about your attempt or the topic…"
          value={draft}
          disabled={busy || waiting}
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
          disabled={busy || waiting || !draft.trim()}
        >
          <SendHorizontal size={16} />
        </button>
      </form>
    </section>
  );
}
