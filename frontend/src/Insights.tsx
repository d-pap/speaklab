import { useRef, useState } from "react";
import { api, errorText, post, timeLabel } from "./api";
import { ErrorNotice } from "./components";
import { processing } from "./Practice";
import { renderMarkdown } from "./markdown";
import { lineLabel } from "./markers";
import type { Attempt, MessagePart } from "./types";

/** Re-run the current coach on a saved attempt. The earlier analysis is archived first. */
export function Rereview({
  attempt,
  onRefresh,
  label = "Re-review with the new coach",
  historyOnly = false,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
  label?: string;
  historyOnly?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<
    | {
        id: number;
        created_at: string;
        attempt: Attempt & {
          review_message?: string;
          review_parts?: MessagePart[];
        };
      }[]
    | null
  >(null);
  async function run() {
    setBusy(true);
    setError("");
    try {
      await post(`/attempts/${attempt.id}/rereview`);
      setHistory(null);
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function loadHistory() {
    try {
      setHistory(await api(`/attempts/${attempt.id}/analysis-history`));
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <div className="rereview">
      {!historyOnly && (
        <p className="small muted">
          The earlier review is archived first. Your recording, transcript and
          review schedule stay unchanged.
        </p>
      )}
      <div className="actions">
        {!historyOnly && (
          <button
            className="button secondary small"
            disabled={busy || processing(attempt)}
            onClick={() => void run()}
          >
            {busy ? "Starting…" : label}
          </button>
        )}
        <button className="text-button" onClick={() => void loadHistory()}>
          {historyOnly ? "View previous reviews" : "View previous analyses"}
        </button>
      </div>
      {error && <ErrorNotice message={error} />}
      {history?.length === 0 && (
        <p className="small muted">No earlier versions archived.</p>
      )}
      {history?.map((h) => (
        <details key={h.id}>
          <summary>
            Saved before re-review · {new Date(h.created_at).toLocaleString()}
          </summary>
          {h.attempt.analysis?.passes?.writer.model && (
            <p className="small muted">
              Review written by {h.attempt.analysis.passes.writer.model}
            </p>
          )}
          {h.attempt.review_message && (
            <div className="archived-review">
              {renderMarkdown(
                (
                  h.attempt.review_parts ?? [
                    { type: "text" as const, text: h.attempt.review_message },
                  ]
                ).map<MessagePart>((part) =>
                  part.type === "text"
                    ? part
                    : {
                        type: "text",
                        text: `${lineLabel(part.line_id, part.start)}${part.quote ? ` “${part.quote}”` : ""}`,
                      },
                ),
                () => {},
              )}
            </div>
          )}
          <details>
            <summary>Transcript for this version</summary>
            <p className="preserve">{h.attempt.transcript}</p>
          </details>
          {h.attempt.assessment?.summary && (
            <p>{h.attempt.assessment.summary}</p>
          )}
          <details>
            <summary>Full saved analysis and measurements</summary>
            <pre className="history-json">
              {JSON.stringify(
                {
                  analysis: h.attempt.analysis,
                  assessment: h.attempt.assessment,
                  acoustics: h.attempt.acoustics,
                  errors: h.attempt.errors,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </details>
      ))}
    </div>
  );
}

/** Play the attempt's recording from a timestamp. Code kept from the earlier DeliveryReview. */
function useTimestampPlayer(attempt: Attempt, label: string) {
  const player = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState("");
  async function listen(time: number) {
    if (!player.current) return;
    setError("");
    player.current.currentTime = Math.max(0, time - 0.3);
    try {
      await player.current.play();
    } catch {
      setError("Press play to listen from the selected timestamp.");
    }
  }
  const marker = (time: number | null, text: string) =>
    time == null ? null : (
      <button
        className="text-button timestamp"
        onClick={() => void listen(time)}
      >
        {timeLabel(time)} · {text}
      </button>
    );
  const audio = (
    <>
      <audio
        ref={player}
        className="full-audio"
        controls
        preload="metadata"
        src={attempt.audio_url}
        aria-label={label}
      />
      {error && (
        <p role="status" className="small muted">
          {error}
        </p>
      )}
    </>
  );
  return { audio, marker };
}

/** Filler words, possible fillers and repetitions, with play-from-timestamp. */
export function FillerDetails({ attempt }: { attempt: Attempt }) {
  const metrics = attempt.acoustics;
  const { audio, marker } = useTimestampPlayer(
    attempt,
    `Listen to filler words in attempt ${attempt.number}`,
  );
  if (metrics?.analysis_version !== 2) return null;
  return (
    <details className="measurement-details">
      <summary>Filler words, possible fillers & repetitions</summary>
      {audio}
      <p className="small muted">
        {attempt.transcription_version === 2
          ? "Verbatim-oriented local transcription"
          : "Original transcription"}{" "}
        · Automatic transcription can omit or add words. Zero detected fillers
        does not mean none were spoken.
      </p>
      <div className="filler-summary">
        <strong>{metrics.filler_count ?? 0} detected hesitations</strong>
        <span>{metrics.fillers_per_minute ?? "—"} / minute</span>
      </div>
      {!!Object.keys(metrics.fillers ?? {}).length && (
        <p className="small">
          Most common first:{" "}
          {Object.entries(metrics.fillers!)
            .map(([word, n]) => `${word} × ${n}`)
            .join(" · ")}
        </p>
      )}
      <p className="small muted">{metrics.note}</p>
      {!!Object.keys(metrics.filler_candidates ?? {}).length && (
        <p className="small">
          Context-dependent candidates:{" "}
          {Object.entries(metrics.filler_candidates!)
            .map(([w, n]) => `${w} × ${n}`)
            .join(" · ")}
          . Excluded from the hesitation total.
        </p>
      )}
      <div className="event-list">
        {metrics.filler_events?.map((event, i) => (
          <div key={i}>
            {marker(event.start, `Hear “${event.text}”`)}{" "}
            <span>
              “{event.text}” ·{" "}
              {event.kind === "hesitation"
                ? "detected hesitation"
                : "review in context"}
            </span>
            <small className="muted">
              {event.timing === "estimated-word"
                ? "Estimated word timestamp"
                : event.timing === "segment"
                  ? "Containing segment start"
                  : "No aligned timestamp"}
            </small>
          </div>
        ))}
      </div>
      {!!metrics.repetitions?.length && (
        <p className="small">
          Repeated phrases:{" "}
          {metrics.repetitions.map((r) => `“${r.text}”`).join(" · ")}.
          Repetition may be intentional emphasis.
        </p>
      )}
    </details>
  );
}

/** The five vocal foundations with practice suggestions and listen-here markers. */
export function VocalFoundations({ attempt }: { attempt: Attempt }) {
  const foundations = attempt.acoustics?.vocal_foundations;
  const { audio, marker } = useTimestampPlayer(
    attempt,
    `Listen to vocal foundations in attempt ${attempt.number}`,
  );
  if (!foundations?.length) return null;
  return (
    <details className="vocal-foundations measurement-details">
      <summary>Vocal foundations · five ways to practice</summary>
      <p className="small muted">
        Measurements suggest places to listen, not a score for confidence or
        charisma. Choose one or two exercises; more variation is not
        automatically better.
      </p>
      {audio}
      {foundations.map((f) => (
        <article className="foundation-card" key={f.foundation}>
          <h4>{f.foundation}</h4>
          <p className="small">{f.observation}</p>
          {marker(f.start, "Listen here")}
          <p>{f.practice}</p>
        </article>
      ))}
    </details>
  );
}

/** The optional, experimental reading-level estimate. */
export function ReadingLevel({ attempt }: { attempt: Attempt }) {
  const reading = attempt.acoustics?.readability;
  if (!reading) return null;
  return (
    <details className="reading-details measurement-details">
      <summary>Optional reading-level estimate · experimental</summary>
      {reading.available && reading.grade_band ? (
        <p>
          <strong>
            Approximate US grade band: {reading.grade_band[0]}–
            {reading.grade_band[1]}
          </strong>
        </p>
      ) : (
        <p>{reading.reason}</p>
      )}
      <p className="small">{reading.limitation}</p>
      <p className="small muted">{reading.basis}</p>
      <p className="small muted">{reading.method}</p>
      {!!reading.repeated_words.length && (
        <p className="small">
          Repeated content words:{" "}
          {reading.repeated_words
            .map((w) => `${w.word} (${w.count})`)
            .join(" · ")}
          . Topic terminology often needs repeating.
        </p>
      )}
    </details>
  );
}
