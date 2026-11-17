import { useState } from "react";
import { CircleHelp, RefreshCw } from "lucide-react";
import { errorText, post, timeLabel } from "./api";
import { ErrorNotice, MiniChart } from "./components";
import type { Acoustics, Attempt, ConceptStatus, PassName } from "./types";

export const conceptLabels: Record<ConceptStatus, string> = {
  correct: "Demonstrated",
  partial: "Developing",
  missing: "Not covered",
  incorrect: "Needs correction",
};
export const conceptName = (id: string) =>
  id.replaceAll("-", " ").replace(/^\w/, (s) => s.toUpperCase());
export const processing = (attempt: Attempt) =>
  ["pending", "processing"].includes(attempt.status);

const PASS_LABELS: Record<PassName, string> = {
  memory: "Coach notes",
  technical: "Technical review",
  communication: "Communication review",
  writer: "Review writer",
};

function phase1Done(attempt: Attempt) {
  const passes = attempt.analysis?.passes;
  return (
    !processing(attempt) &&
    passes?.technical.status === "done" &&
    passes?.communication.status === "done"
  );
}

/** True while a review is on its way; mirrors the backend's chat gate. */
export function reviewing(attempt: Attempt) {
  if (processing(attempt)) return true;
  const writer = attempt.analysis?.passes?.writer.status;
  if (writer === "waiting") return true;
  return (
    (writer === "pending" || writer === "running") &&
    attempt.status !== "interrupted" &&
    phase1Done(attempt)
  );
}

/** One line of pass progress, e.g. "Reading the technical side… the communication side… writing". */
export function progressLine(attempt: Attempt): string | null {
  const passes = attempt.analysis?.passes;
  if (!passes) return processing(attempt) ? "Listening and measuring…" : null;
  if (!reviewing(attempt)) return null;
  if (passes.writer.status === "waiting")
    return "Your review is written once you send or skip your note.";
  const remaining = (["technical", "communication"] as const)
    .filter((name) => ["pending", "running"].includes(passes[name].status))
    .map((name) =>
      name === "technical" ? "the technical side" : "the communication side",
    );
  if (!remaining.length) return "Writing your review…";
  return `Reading ${remaining.join("… ")}… writing`;
}

export function AttemptStatus({
  attempt,
  onRefresh,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function retry() {
    setBusy(true);
    setError("");
    try {
      await post(`/attempts/${attempt.id}/retry`);
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const progress = progressLine(attempt);
  const failed = (
    Object.entries(attempt.analysis?.passes ?? {}) as [
      PassName,
      { status: string; error: string | null },
    ][]
  ).filter(([, p]) => p.status === "failed");
  const attemptErrors = processing(attempt)
    ? []
    : Object.entries(attempt.errors ?? {});
  const retryButton = (
    <button
      className="text-button"
      disabled={busy || processing(attempt)}
      onClick={() => void retry()}
    >
      <RefreshCw size={14} />
      {busy ? "Retrying…" : "Retry"}
    </button>
  );
  return (
    <>
      {progress && (
        <div className="notice progress-line" role="status">
          <RefreshCw size={17} className="spin" />
          <div>
            <strong>{progress}</strong>
            <p>Your audio is saved. The transcript appears first.</p>
          </div>
        </div>
      )}
      {(attemptErrors.length > 0 ||
        failed.length > 0 ||
        attempt.status === "interrupted") && (
        <div className="notice warning">
          <CircleHelp size={18} />
          <div>
            <strong>
              Your recording is safe. Some analysis is unavailable.
            </strong>
            {attemptErrors.map(([k, v]) => (
              <p key={k}>{v}</p>
            ))}
            {attempt.status === "interrupted" && !failed.length && (
              <p>The review stopped before it finished.</p>
            )}
            {failed.map(([name, p]) => (
              <div className="failed-pass" key={name}>
                <p>
                  <strong>{PASS_LABELS[name]}:</strong> {p.error}
                </p>
                {retryButton}
              </div>
            ))}
            {!failed.length && retryButton}
          </div>
        </div>
      )}
      {error && <ErrorNotice message={error} />}
    </>
  );
}

export function AcousticPanel({
  metrics,
  duration,
}: {
  metrics: Acoustics | null;
  duration: number;
}) {
  if (!metrics)
    return (
      <p className="muted">
        Acoustic measurements will appear after your saved audio is processed.
      </p>
    );
  const metric = (v: number | null | undefined, unit = "") =>
    v == null ? "—" : `${v}${unit}`;
  return (
    <>
      <span className="eyebrow">MEASURED FROM YOUR RECORDING</span>
      <div className="metric-grid">
        <div>
          <strong>{metric(metrics.wpm)}</strong>
          <span>words / minute</span>
        </div>
        <div>
          <strong>{metric(metrics.pause_count)}</strong>
          <span>internal pauses</span>
        </div>
        <div>
          <strong>{metric(metrics.filler_count)}</strong>
          <span>transcribed fillers</span>
        </div>
        <div>
          <strong>{metric(metrics.pitch_range_semitones, " st")}</strong>
          <span>pitch spread · P10–P90</span>
        </div>
      </div>
      <p className="small muted">
        {metrics.active_fraction != null
          ? `${Math.round(metrics.active_fraction * 100)}% energy-active audio · `
          : ""}
        {metrics.loudness_range_db != null
          ? `${metrics.loudness_range_db} dB relative loudness spread`
          : "Loudness spread unavailable"}
      </p>
      {!!metrics.fillers && Object.keys(metrics.fillers).length > 0 && (
        <div className="tag-row">
          {Object.entries(metrics.fillers).map(([term, count]) => (
            <span className="tag" key={term}>
              “{term}” × {count}
            </span>
          ))}
        </div>
      )}
      <details className="measurement-details">
        <summary>Explore the audio timeline</summary>
        <MiniChart
          points={metrics.loudness_track}
          label="Relative loudness"
          unit="dBFS"
          duration={duration}
        />
        <MiniChart
          points={metrics.pitch_track}
          label="Estimated pitch"
          unit="Hz"
          duration={duration}
        />
        <MiniChart
          points={metrics.rate_track}
          label="Estimated rate · 30-second windows"
          unit="WPM"
          duration={duration}
        />
        {!!metrics.pauses?.length && (
          <p className="small muted">
            Pauses:{" "}
            {metrics.pauses
              .map((p) => `${timeLabel(p.start)} (${p.duration}s)`)
              .join(" · ")}
          </p>
        )}
        {!!metrics.extended_silences?.length && (
          <p className="small muted">
            Long silences (including edges):{" "}
            {metrics.extended_silences
              .map((p) => `${timeLabel(p.start)} (${p.duration}s)`)
              .join(" · ")}
          </p>
        )}
        <p className="small muted">{metrics.note}</p>
        {metrics.limitations?.map((l) => (
          <p className="small muted" key={l}>
            {l}
          </p>
        ))}
      </details>
      {!!metrics.suggestions?.length && (
        <div className="coaching">
          <span className="eyebrow">TRY THIS · TENTATIVE COACHING</span>
          {metrics.suggestions.map((s, i) => (
            <p key={s}>
              <span>{i + 1}</span>
              {s}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
