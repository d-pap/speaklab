import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleHelp,
  RefreshCw,
  Volume2,
} from "lucide-react";
import {
  AccuracyReview,
  DeliveryReview,
  VocabularyReview,
  Reanalyze,
} from "./Insights";
import { api, dateLabel, errorText, post, put, timeLabel } from "./api";
import { ErrorNotice, Loading, MiniChart, NextButton } from "./components";
import { VocalVariation } from "./VocalVariation";
import { paceRange } from "./vocalMetrics";
import type {
  Acoustics,
  Attempt,
  Comparison,
  ConceptStatus,
  Session,
} from "./types";

const labels: Record<ConceptStatus, string> = {
  correct: "Demonstrated",
  partial: "Developing",
  missing: "Not covered",
  incorrect: "Needs correction",
};
const conceptName = (id: string) =>
  id.replaceAll("-", " ").replace(/^\w/, (s) => s.toUpperCase());
export const processing = (attempt: Attempt) =>
  ["pending", "processing"].includes(attempt.status);

function Transcript({
  attempt,
  onRefresh,
  locked,
}: {
  attempt: Attempt;
  onRefresh: () => Promise<void>;
  locked?: boolean;
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
    <details className="transcript-panel">
      <summary>
        Transcript{" "}
        <span className="subtle">
          {attempt.transcript_source === "manual"
            ? "Manually edited · timestamps cleared"
            : attempt.transcript
              ? "Local transcription"
              : "Not available yet"}
        </span>
      </summary>
      <div className="transcript-content">
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
              Saving clears the old assessment and recalculates feedback. Audio
              stays unchanged. Manual transcripts have no timing alignment.
            </p>
            <div className="actions">
              <button
                className="button primary small"
                disabled={busy || !text.trim()}
                onClick={() => void save()}
              >
                {busy ? "Saving…" : "Save & reanalyze"}
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
          <>
            <p className="preserve">
              {attempt.transcript ||
                "Transcription is unavailable. You can enter a transcript from your recording to enable technical feedback."}
            </p>
            {!!attempt.segments?.length && (
              <details className="segment-list">
                <summary>View timestamped segments</summary>
                {attempt.segments.map((s, i) => (
                  <p key={i}>
                    <span className="mono">{timeLabel(s.start)}</span> {s.text}
                  </p>
                ))}
              </details>
            )}
            {!locked && (
              <button
                className="text-button"
                disabled={processing(attempt)}
                onClick={() => setEditing(true)}
              >
                {attempt.transcript
                  ? "Edit transcript"
                  : "Enter transcript manually"}
              </button>
            )}
          </>
        )}
        {error && <ErrorNotice message={error} />}
      </div>
    </details>
  );
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
  return (
    <>
      {processing(attempt) ? (
        <div className="notice">
          <RefreshCw size={17} className="spin" />
          <div>
            <strong>
              {attempt.status === "pending"
                ? "Queued for local analysis"
                : "Listening, measuring, and reviewing…"}
            </strong>
            <p>
              Your audio is saved. Local analysis can take a few minutes. You
              can begin the lesson while it runs.
            </p>
          </div>
        </div>
      ) : (
        Object.keys(attempt.errors ?? {}).length > 0 && (
          <div className="notice warning">
            <CircleHelp size={18} />
            <div>
              <div className="eyebrow">ATTEMPT {attempt.number}</div>
              <strong>
                Your recording is safe. Some analysis is unavailable.
              </strong>
              {Object.entries(attempt.errors).map(([k, v]) => (
                <p key={k}>{v}</p>
              ))}
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void retry()}
              >
                <RefreshCw size={14} />
                {busy ? "Retrying…" : "Retry unavailable analysis"}
              </button>
            </div>
          </div>
        )
      )}
      {error && <ErrorNotice message={error} />}
    </>
  );
}

function AcousticPanel({
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

export function Feedback({
  session,
  onRefresh,
  onNext,
}: {
  session: Session;
  onRefresh: () => Promise<void>;
  onNext: () => void;
}) {
  const attempt = session.attempts[0];
  if (!attempt) return null;
  return (
    <div className="stack">
      <div className="page-heading">
        <span className="eyebrow">ATTEMPT 01 · REFLECT</span>
        <h1>Your first explanation</h1>
        <p>{session.topic.title} · Review your understanding and delivery.</p>
      </div>
      <AttemptStatus attempt={attempt} onRefresh={onRefresh} />
      <div className="feedback-grid">
        <section className="panel">
          <div className="panel-heading">
            <BookOpen size={19} />
            <h2>Technical understanding</h2>
          </div>
          {attempt.assessment ? (
            <>
              <p>{attempt.assessment.summary}</p>
              <AccuracyReview attempt={attempt} />
              <h3>Concept coverage</h3>
              <div className="concept-list">
                {attempt.assessment.concepts.map((c) => (
                  <details key={c.concept_id}>
                    <summary>
                      <span>{conceptName(c.concept_id)}</span>
                      <span className={`status-badge ${c.status}`}>
                        {labels[c.status]}
                      </span>
                    </summary>
                    <p>{c.feedback}</p>
                    {c.evidence && <blockquote>“{c.evidence}”</blockquote>}
                  </details>
                ))}
              </div>
              <div className="next-steps">
                <span className="eyebrow">FOCUS ON THESE NEXT</span>
                {attempt.assessment.next_steps.map((s, i) => (
                  <p key={s}>
                    <span>{i + 1}</span>
                    {s}
                  </p>
                ))}
              </div>
              <p className="small muted">
                {attempt.assessment.rubric} Reviewed by{" "}
                {attempt.assessment.model}; treat the feedback as a useful
                hypothesis to check against the lesson.
              </p>
            </>
          ) : (
            <div className="unavailable">
              <BookOpen size={28} />
              <h3>
                {processing(attempt)
                  ? "Finding the gaps worth exploring"
                  : "Technical feedback isn’t available yet"}
              </h3>
              <p>
                A local model and a transcript are needed for assessment. The
                reference lesson is ready whenever you are.
              </p>
            </div>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <Volume2 size={19} />
            <h2>Communication & voice</h2>
          </div>
          <VocalVariation attempt={attempt} style={session.style} />
          <details className="measurement-details overall-measurements">
            <summary>Overall measurements & recording limits</summary>
            <AcousticPanel
              metrics={attempt.acoustics}
              duration={attempt.duration}
            />
          </details>
          {!!attempt.assessment?.communication.length && (
            <div className="coaching">
              <span className="eyebrow">TRANSCRIPT-BASED COACHING</span>
              {attempt.assessment.communication.map((c) => (
                <div key={c.suggestion}>
                  <p>{c.suggestion}</p>
                  <blockquote>“{c.evidence}”</blockquote>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      <div className="feedback-grid">
        <details className="panel review-disclosure">
          <summary>Vocal foundations & recording details</summary>
          <DeliveryReview attempt={attempt} />
        </details>
        <details className="panel review-disclosure">
          <summary>Vocabulary & further analysis</summary>
          <VocabularyReview attempt={attempt} />
          <Reanalyze attempt={attempt} onRefresh={onRefresh} />
        </details>
      </div>
      <Transcript
        attempt={attempt}
        onRefresh={onRefresh}
        locked={!!session.completed_at}
      />
      <div className="page-actions">
        <p className="muted small">
          A gap is a starting point. Let’s work through it.
        </p>
        <NextButton onClick={onNext}>Build your understanding</NextButton>
      </div>
    </div>
  );
}

export function ComparisonView({
  session,
  onRefresh,
  onHome,
}: {
  session: Session;
  onRefresh: () => Promise<void>;
  onHome: () => void;
}) {
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [recall, setRecall] = useState("good");
  const [busy, setBusy] = useState(false);
  const [first, second] = session.attempts;
  useEffect(() => {
    let alive = true;
    api<Comparison>(`/sessions/${session.id}/comparison`)
      .then((r) => {
        if (alive) setComparison(r);
      })
      .catch((e) => {
        if (alive) setError(errorText(e));
      });
    return () => {
      alive = false;
    };
  }, [
    session.id,
    first?.status,
    second?.status,
    first?.assessment,
    second?.assessment,
  ]);
  async function finish() {
    setBusy(true);
    setError("");
    try {
      await post(`/sessions/${session.id}/complete`, { recall });
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (!first || !second) return <Loading />;
  const correct = (a: Attempt) =>
    a.assessment?.concepts.filter((c) => c.status === "correct").length;
  const metric = (a: Attempt, k: keyof Acoustics, suffix = "") =>
    a.acoustics?.[k] == null ? "—" : `${a.acoustics[k]}${suffix}`;
  return (
    <div className="stack">
      <div className="page-heading">
        <span className="eyebrow">
          REFLECT ·{" "}
          {session.completed_at
            ? "SESSION COMPLETE"
            : "BOTH ATTEMPTS, SIDE BY SIDE"}
        </span>
        <h1>Before & after</h1>
        <p>
          {session.topic.title} · Notice what changed, and what still needs
          time.
        </p>
      </div>
      <AttemptStatus attempt={second} onRefresh={onRefresh} />
      {first.status !== "ready" && (
        <AttemptStatus attempt={first} onRefresh={onRefresh} />
      )}
      {error && <ErrorNotice message={error} />}
      <div className="comparison-hero">
        <div>
          <span className="eyebrow">UNDERSTANDING, MADE VISIBLE</span>
          <h2>
            {comparison?.available
              ? `${comparison.newly_demonstrated.length} more concept${comparison.newly_demonstrated.length === 1 ? "" : "s"} demonstrated.`
              : "Your two explanations are saved."}
          </h2>
          <p>
            {comparison?.available
              ? `${comparison.corrected.length} explicit misconception${comparison.corrected.length === 1 ? "" : "s"} corrected. ${comparison.remaining.length} concepts still worth revisiting.`
              : "Complete local analysis to see concept-level changes. You can still listen, reflect, and schedule a review."}
          </p>
        </div>
        <div className="coverage-comparison">
          <div>
            <strong>{correct(first) ?? "—"}</strong>
            <span>Before</span>
          </div>
          <ArrowRight size={24} />
          <div>
            <strong>{correct(second) ?? "—"}</strong>
            <span>After</span>
          </div>
        </div>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <BookOpen size={19} />
          <h2>Technical understanding</h2>
        </div>
        <p className="small muted">
          Concept counts use the same reference rubric. Missing is different
          from incorrect; these are model judgments, not grades.
        </p>
        <div className="table-wrap">
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Reference concept</th>
                <th>Cold explanation</th>
                <th>After learning</th>
              </tr>
            </thead>
            <tbody>
              {comparison?.concepts.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  {[first, second].map((a) => {
                    const r = a.assessment?.concepts.find(
                      (v) => v.concept_id === c.id,
                    );
                    return (
                      <td key={a.id}>
                        {r ? (
                          <details>
                            <summary>
                              <span className={`status-badge ${r.status}`}>
                                {labels[r.status]}
                              </span>
                            </summary>
                            <p className="small">{r.feedback}</p>
                            {r.evidence && (
                              <blockquote>“{r.evidence}”</blockquote>
                            )}
                          </details>
                        ) : (
                          <span className="muted">Awaiting assessment</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <Volume2 size={19} />
          <h2>How your delivery changed</h2>
        </div>
        <p className="small muted">
          Different is not automatically better. Compare with your intended{" "}
          {session.style.toLowerCase()} style, using the same microphone and
          setup.
        </p>
        <div className="table-wrap">
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Measurement</th>
                <th>Cold explanation</th>
                <th>After learning</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Estimated pace range · full 30s windows</td>
                <td>{paceRange(first.acoustics, first.duration)}</td>
                <td>{paceRange(second.acoustics, second.duration)}</td>
              </tr>
              {(
                [
                  ["Speaking rate", "wpm", " WPM"],
                  ["Internal pauses ≥ 0.3s", "pause_count", ""],
                  ["Time in internal pauses", "pause_seconds", " s"],
                  ["Detected hesitations", "filler_count", ""],
                  ["Hesitations per minute", "fillers_per_minute", ""],
                  ["Pitch spread · P10–P90", "pitch_range_semitones", " st"],
                  ["Loudness spread · P10–P90", "loudness_range_db", " dB"],
                ] as [string, keyof Acoustics, string][]
              ).map(([label, key, unit]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td>{metric(first, key, unit)}</td>
                  <td>{metric(second, key, unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="feedback-grid">
        {[first, second].map((a) => (
          <section className="panel" key={a.id}>
            <span className="eyebrow">
              ATTEMPT {a.number === 1 ? "01 · BEFORE" : "02 · AFTER"}
            </span>
            <h3>
              {a.number === 1 ? "Your starting point" : "Your new explanation"}
            </h3>
            <details className="attempt-detail">
              <summary>
                Factual accuracy & vocabulary · attempt {a.number}
              </summary>
              <AccuracyReview attempt={a} />
              <VocabularyReview attempt={a} />
            </details>
            <details className="attempt-detail">
              <summary>Vocal variation · attempt {a.number}</summary>
              <VocalVariation attempt={a} style={session.style} />
            </details>
            <DeliveryReview attempt={a} />
            <Reanalyze attempt={a} onRefresh={onRefresh} />
            {a.assessment?.communication.map((p) => (
              <div key={p.suggestion} className="comparison-coaching">
                <p className="small">{p.suggestion}</p>
                <blockquote>“{p.evidence}”</blockquote>
              </div>
            ))}
            <Transcript
              attempt={a}
              onRefresh={onRefresh}
              locked={!!session.completed_at}
            />
          </section>
        ))}
      </div>
      <section className="retention-note">
        <BookOpen size={21} />
        <div>
          <h3>Learning now. Remembering later.</h3>
          <p>
            {comparison?.prior_session?.available &&
            comparison.prior_session.days_elapsed > 0
              ? `Your cold attempt recalled ${comparison.prior_session.recalled} of ${comparison.prior_session.previously_demonstrated} concepts demonstrated ${comparison.prior_session.days_elapsed} days ago. This is early evidence of retention, subject to model judgment.`
              : "This session shows immediate learning. Your next cold explanation, on a different day, will help reveal what stuck."}
          </p>
        </div>
      </section>
      {session.completed_at ? (
        <div className="completion-card">
          <div>
            <Check size={22} />
            <div>
              <h3>A good place to leave it.</h3>
              <p>
                Your next memory check is scheduled for{" "}
                {dateLabel(session.review_due!)}.
              </p>
            </div>
          </div>
          <button className="button primary" onClick={onHome}>
            Back to today <ArrowRight size={17} />
          </button>
        </div>
      ) : (
        <section className="panel finish-panel">
          <div>
            <h2>How solid does the idea feel?</h2>
            <p className="muted small">
              Your recall rating sets the next review. Missing concepts can
              shorten the interval.
            </p>
            <div className="recall-options">
              {[
                ["again", "Still unclear"],
                ["hard", "A little shaky"],
                ["good", "Makes sense"],
                ["easy", "I can teach it"],
              ].map(([value, label]) => (
                <button
                  className={recall === value ? "selected" : ""}
                  key={value}
                  aria-pressed={recall === value}
                  onClick={() => setRecall(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <button
            className="button primary"
            disabled={busy || session.attempts.some(processing)}
            onClick={() => void finish()}
          >
            {busy ? "Saving…" : "Finish & schedule review"}
            <Check size={17} />
          </button>
        </section>
      )}
    </div>
  );
}
