import { useEffect, useRef, useState, type ReactNode } from "react";
import { errorText, put, timeLabel } from "./api";
import { ErrorNotice } from "./components";
import { processing } from "./Practice";
import type { Attempt, Line, Token } from "./types";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The quiet summary above the transcript, e.g. "1:56 · 1 filler, 1 possible · 3 pauses over 1s · longest 1.6s". */
export function statsLine(attempt: Attempt): string {
  const stats = attempt.analysis?.stats ?? {};
  const parts = [timeLabel(stats.duration ?? attempt.duration)];
  if (stats.fillers != null) {
    let fillers = plural(stats.fillers, "filler");
    if (stats.possible_fillers)
      fillers += `, ${stats.possible_fillers} possible`;
    parts.push(fillers);
  }
  if (stats.pauses_over_1s != null)
    parts.push(`${plural(stats.pauses_over_1s, "pause")} over 1s`);
  if (stats.longest_pause != null)
    parts.push(`longest ${stats.longest_pause.toFixed(1)}s`);
  return parts.join(" · ");
}

function renderTokens(tokens: Token[]): ReactNode[] {
  const out: ReactNode[] = [];
  tokens.forEach((token, i) => {
    if (i > 0) out.push(" ");
    if (token.type === "pause")
      out.push(
        <span className="pause" key={i}>
          {token.seconds.toFixed(1)}s
        </span>,
      );
    else if (token.type === "filler")
      out.push(
        <mark className="filler" key={i}>
          {token.text}
        </mark>,
      );
    else if (token.type === "possible_filler")
      out.push(
        <mark className="filler possible" key={i}>
          {token.text}
        </mark>,
      );
    else out.push(token.text);
  });
  return out;
}

export function TranscriptTab({
  attempt,
  highlighted,
  highlightTick = 0,
}: {
  attempt: Attempt;
  highlighted: string | null;
  highlightTick?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const lines: Line[] = attempt.lines ?? [];
  useEffect(() => {
    if (!highlighted) return;
    const target = container.current?.querySelector(
      `[data-line="${CSS.escape(highlighted)}"]`,
    );
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlighted, highlightTick]);
  const byLine = new Map<string, Token[]>();
  for (const token of attempt.tokens ?? []) {
    const list = byLine.get(token.line_id) ?? [];
    list.push(token);
    byLine.set(token.line_id, list);
  }
  return (
    <div className="transcript-tab" ref={container}>
      {lines.length > 0 ? (
        <>
          <p className="stats-line">{statsLine(attempt)}</p>
          <div className="tx">
            {lines.map((line) => (
              <p
                key={line.id}
                data-line={line.id}
                className={`tx-line ${highlighted === line.id ? "highlight" : ""}`}
              >
                {line.start != null && (
                  <span className="ts">{timeLabel(line.start)}</span>
                )}
                {byLine.has(line.id)
                  ? renderTokens(byLine.get(line.id)!)
                  : line.text}
              </p>
            ))}
          </div>
          {attempt.transcript_source === "manual" && (
            <p className="small muted">
              Manually edited transcript: no line times or pause marks.
            </p>
          )}
        </>
      ) : attempt.transcript ? (
        <p className="preserve tx">{attempt.transcript}</p>
      ) : (
        <p className="muted">
          {processing(attempt)
            ? "The transcript appears here once your recording is transcribed."
            : "Transcription is unavailable. You can enter a transcript from your recording."}
        </p>
      )}
    </div>
  );
}

/** Correct or enter the transcript by hand. Saving starts a fresh review. */
export function TranscriptEditor({
  attempt,
  onRefresh,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(attempt.transcript ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!editing) setText(attempt.transcript ?? "");
  }, [attempt.transcript, editing]);
  async function save() {
    setBusy(true);
    setError("");
    try {
      await put(`/attempts/${attempt.id}/transcript`, { text });
      setEditing(false);
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="transcript-editor">
      {editing ? (
        <>
          <label className="field-label" htmlFor={`transcript-${attempt.id}`}>
            Correct or enter what you said
          </label>
          <textarea
            id={`transcript-${attempt.id}`}
            rows={8}
            maxLength={30000}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="small muted">
            Saving starts a fresh review; the earlier one is archived. Audio
            stays unchanged. Manual transcripts have no line times.
          </p>
          <div className="actions">
            <button
              className="button primary small"
              disabled={busy || !text.trim()}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save & review again"}
            </button>
            <button
              className="button ghost small"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <button
          className="text-button"
          disabled={processing(attempt)}
          onClick={() => setEditing(true)}
        >
          {attempt.transcript ? "Edit transcript" : "Enter transcript manually"}
        </button>
      )}
      {error && <ErrorNotice message={error} />}
    </div>
  );
}
