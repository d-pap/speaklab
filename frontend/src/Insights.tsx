import { useRef, useState } from "react";
import { api, errorText, post, timeLabel } from "./api";
import { ErrorNotice } from "./components";
import type { Attempt } from "./types";

export function AccuracyReview({ attempt }: { attempt: Attempt }) {
  const review = attempt.assessment?.insights;
  const names = {
    supported: "Supported by reference",
    incorrect: "Needs correction",
    needs_nuance: "Needs qualification",
    unverified: "Not verified",
  };
  return (
    <div className="insight-section">
      <h3>Was my explanation accurate?</h3>
      {!review ? (
        <p className="small muted">
          The separate factual review is not available yet. Existing concept
          feedback remains below; use reanalysis to add the latest review.
        </p>
      ) : (
        <>
          <p className="small muted">{review.note}</p>
          {!review.claims.length && (
            <p>
              No substantive claims were selected for review. This does not
              certify every statement as correct.
            </p>
          )}
          {review.claims.map((claim, i) => (
            <article key={i} className={`claim-card ${claim.verdict}`}>
              <span className="tag">{names[claim.verdict]}</span>
              <blockquote>“{claim.evidence}”</blockquote>
              <p>{claim.explanation}</p>
              {claim.correction && (
                <p>
                  <strong>A more accurate explanation: </strong>
                  {claim.correction}
                </p>
              )}
              {!!claim.references.length && (
                <details>
                  <summary>Why · reference grounding</summary>
                  {claim.references.map((ref) => (
                    <p className="small" key={ref.id}>
                      {ref.text}
                    </p>
                  ))}
                  {review.sources.map((s) => (
                    <a
                      className="source-link"
                      key={s.url}
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {s.title} ↗
                    </a>
                  ))}
                </details>
              )}
            </article>
          ))}
        </>
      )}
    </div>
  );
}

export function VocabularyReview({ attempt }: { attempt: Attempt }) {
  const review = attempt.assessment?.insights;
  const reading = attempt.acoustics?.readability;
  return (
    <div className="insight-section">
      <h3>Build your vocabulary</h3>
      <p className="small muted">
        Optional model suggestions to try next time. Your original wording may
        already be clear. Choose alternatives that help your audience; longer
        words and acronyms are not automatically better.
      </p>
      {review ? (
        review.vocabulary.length ? (
          review.vocabulary.map((v, i) => (
            <article className="vocabulary-card" key={i}>
              <p>
                <span className="muted">You said </span>“{v.original}”{" "}
                <span aria-hidden="true">→</span>{" "}
                <strong>{v.alternative}</strong>
              </p>
              <p>{v.meaning}</p>
              <p className="small">{v.reason}</p>
              <details>
                <summary>Practice this wording</summary>
                <p>{v.practice}</p>
                <blockquote>Original context: “{v.evidence}”</blockquote>
              </details>
            </article>
          ))
        ) : (
          <p className="small">
            No specific word changes suggested for this attempt. Clear simple
            wording is worth keeping.
          </p>
        )
      ) : (
        <p className="small muted">
          Vocabulary suggestions need the local model review.
        </p>
      )}
      {reading && (
        <details className="reading-details">
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
      )}
    </div>
  );
}

export function DeliveryReview({ attempt }: { attempt: Attempt }) {
  const player = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState("");
  const metrics = attempt.acoustics;
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
  const marker = (time: number | null, label: string) =>
    time == null ? null : (
      <button
        className="text-button timestamp"
        onClick={() => void listen(time)}
      >
        {timeLabel(time)} · {label}
      </button>
    );
  const highlight = (text: string) =>
    text
      .split(/(\b(?:u+m+|u+h+|e+r+m+|h+m+)\b)/gi)
      .map((part, i) =>
        /^(?:u+m+|u+h+|e+r+m+|h+m+)$/i.test(part) ? (
          <mark key={i}>{part}</mark>
        ) : (
          part
        ),
      );
  const timeline = [
    ...(attempt.segments ?? []).map((s) => ({
      start: s.start,
      type: "speech",
      text: s.text,
    })),
    ...(metrics?.pauses ?? []).map((p) => ({
      start: p.start,
      type: "pause",
      text: `[pause: ${p.duration.toFixed(1)}s]`,
    })),
  ].sort((a, b) => a.start - b.start);
  return (
    <div className="insight-section delivery-review">
      <h3>Listen to the details</h3>
      <audio
        ref={player}
        className="full-audio"
        controls
        preload="metadata"
        src={attempt.audio_url}
        aria-label={`Review attempt ${attempt.number} by timestamp`}
      />
      {error && (
        <p role="status" className="small muted">
          {error}
        </p>
      )}
      <p className="small muted">
        {attempt.transcription_version === 2
          ? "Verbatim-oriented local transcription"
          : "Original transcription"}{" "}
        · Automatic transcription can omit or add words. Zero detected fillers
        does not mean none were spoken.
      </p>
      {metrics?.analysis_version === 2 && (
        <>
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
          <details>
            <summary>Filler words, possible fillers & repetitions</summary>
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
        </>
      )}
      <details className="annotated-transcript">
        <summary>Annotated transcript & measured pauses</summary>
        <p className="small muted">
          Speech segments and audio-derived pauses are ordered by start time. A
          pause may fall inside a segment; its marker does not imply an exact
          word boundary. Highlighted hesitations are what transcription
          detected.
        </p>
        {!attempt.segments?.length && (
          <p className="preserve">
            {highlight(attempt.transcript ?? "No transcript available.")}
          </p>
        )}
        {timeline.map((event, i) => (
          <div className={`timeline-row ${event.type}`} key={i}>
            {marker(
              event.start,
              event.type === "pause" ? "Hear pause" : "Play passage",
            )}
            <p>
              {event.type === "speech" ? highlight(event.text) : event.text}
            </p>
          </div>
        ))}
      </details>
      {!!metrics?.vocal_foundations?.length && (
        <details className="vocal-foundations">
          <summary>Vocal foundations · five ways to practice</summary>
          <p className="small muted">
            Measurements suggest places to listen, not a score for confidence or
            charisma. Choose one or two exercises; more variation is not
            automatically better.
          </p>
          {metrics.vocal_foundations.map((f) => (
            <article className="foundation-card" key={f.foundation}>
              <h4>{f.foundation}</h4>
              <p className="small">{f.observation}</p>
              {marker(f.start, "Listen here")}
              <p>{f.practice}</p>
            </article>
          ))}
        </details>
      )}
    </div>
  );
}

export function Reanalyze({
  attempt,
  onRefresh,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [retranscribe, setRetranscribe] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<
    { id: number; created_at: string; attempt: Attempt }[] | null
  >(null);
  async function run() {
    setBusy(true);
    setError("");
    try {
      await post(`/attempts/${attempt.id}/reanalyze`, { retranscribe });
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
    <details className="reanalysis">
      <summary>Reanalyze & previous versions</summary>
      <p className="small muted">
        Use the latest feedback on this recording. The previous transcript and
        analysis are archived first. Audio and your scheduled review date stay
        unchanged.
      </p>
      {attempt.transcript_source !== "manual" && (
        <label className="retranscribe-choice">
          <input
            type="checkbox"
            checked={retranscribe}
            onChange={(e) => setRetranscribe(e.target.checked)}
          />{" "}
          Also transcribe again with the verbatim-oriented settings
        </label>
      )}
      <div className="actions">
        <button
          className="button secondary small"
          disabled={busy || ["pending", "processing"].includes(attempt.status)}
          onClick={() => void run()}
        >
          Analyze with latest feedback
        </button>
        <button className="text-button" onClick={() => void loadHistory()}>
          View previous analyses
        </button>
      </div>
      {error && <ErrorNotice message={error} />}
      {history?.length === 0 && (
        <p className="small muted">No earlier versions archived.</p>
      )}
      {history?.map((h) => (
        <details key={h.id}>
          <summary>
            Saved before reanalysis · {new Date(h.created_at).toLocaleString()}
          </summary>
          <p className="preserve">{h.attempt.transcript}</p>
          <p>{h.attempt.assessment?.summary}</p>
          <details>
            <summary>Full saved feedback and measurements</summary>
            <pre className="history-json">
              {JSON.stringify(
                {
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
    </details>
  );
}
