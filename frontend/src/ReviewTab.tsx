import { useState } from "react";
import { Rereview } from "./Insights";
import { lineLabel } from "./markers";
import { conceptLabels, conceptName, processing } from "./Practice";
import type {
  Attempt,
  ReviewStructure,
  Score,
  TechnicalAnalysis,
} from "./types";

export const CORE_SCORES = [
  "Overall",
  "Clarity",
  "Structure",
  "Conciseness",
  "Technical accuracy",
  "Technical coverage",
  "Handling uncertainty",
];

export const scoreText = (score: number) => score.toFixed(1);

/** The attempt's review structure, or null when there is none (yet) or it was too short. */
export function reviewStructure(attempt?: Attempt): ReviewStructure | null {
  const review = attempt?.analysis?.review;
  return review && !("too_short" in review) ? review : null;
}

export const isTooShort = (attempt?: Attempt) => {
  const review = attempt?.analysis?.review;
  return !!review && "too_short" in review && review.too_short;
};

function orderScores(scores: Score[]) {
  const rank = (s: Score) => {
    const i = CORE_SCORES.indexOf(s.name);
    return i < 0 ? CORE_SCORES.length : i;
  };
  return scores
    .map((s, i) => ({ s, i }))
    .sort((a, b) => rank(a.s) - rank(b.s) || a.i - b.i)
    .map(({ s }) => s);
}

function LineRefs({
  attempt,
  ids,
  onRef,
}: {
  attempt: Attempt;
  ids: string[];
  onRef?: (lineId: string) => void;
}) {
  const lines = attempt.lines ?? [];
  return (
    <>
      {ids.map((id) => {
        const line = lines.find((l) => l.id === id);
        if (!line) return null;
        return (
          <button
            key={id}
            type="button"
            className="time-ref"
            onClick={() => onRef?.(id)}
          >
            {lineLabel(id, line.start)}
          </button>
        );
      })}
    </>
  );
}

function TechnicalDetails({
  attempt,
  technical,
  onRef,
}: {
  attempt: Attempt;
  technical: TechnicalAnalysis;
  onRef?: (lineId: string) => void;
}) {
  return (
    <div className="technical-details">
      <h4>Concepts</h4>
      <ul className="plain-list">
        {technical.concepts.map((c) => (
          <li key={c.concept_id}>
            <strong>{conceptName(c.concept_id)}</strong>{" "}
            <span className={`status-badge ${c.status}`}>
              {conceptLabels[c.status]}
            </span>{" "}
            <LineRefs attempt={attempt} ids={c.line_ids} onRef={onRef} />
            {c.note && <p className="small">{c.note}</p>}
          </li>
        ))}
      </ul>
      {technical.corrections.length > 0 && (
        <>
          <h4>Corrections</h4>
          <ul className="plain-list">
            {technical.corrections.map((c, i) => (
              <li key={i}>
                <LineRefs attempt={attempt} ids={[c.line_id]} onRef={onRef} />{" "}
                {c.basis === "model" ? (
                  <span className="tag">Not in reference</span>
                ) : (
                  c.verified === false && (
                    <span className="tag">Unverified</span>
                  )
                )}
                <p className="small">{c.claim}</p>
                <p>{c.correction}</p>
              </li>
            ))}
          </ul>
        </>
      )}
      {technical.senior_points.length > 0 && (
        <>
          <h4>What a senior engineer would cover</h4>
          <ul className="plain-list">
            {technical.senior_points.map((p, i) => (
              <li key={i}>
                {p.point}{" "}
                {p.basis === "model" && (
                  <span className="tag">Not in reference</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function ReviewTab({
  attempt,
  previous,
  onRef,
  onRefresh,
  onRecordAgain,
}: {
  attempt: Attempt;
  previous?: Attempt;
  onRef?: (lineId: string) => void;
  onRefresh?: () => Promise<void>;
  onRecordAgain?: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const review = reviewStructure(attempt);
  const technical = attempt.analysis?.technical;
  const warning = attempt.analysis?.passes?.writer.warning;
  // Earlier analyses (archived by re-review or a transcript edit) stay viewable on every attempt.
  const history =
    onRefresh && !processing(attempt) ? (
      <details className="review-details">
        <summary>Earlier versions and re-review</summary>
        <Rereview
          attempt={attempt}
          onRefresh={onRefresh}
          label="Re-review this attempt"
        />
      </details>
    ) : null;

  if (attempt.note_state === "legacy" && attempt.assessment) {
    const a = attempt.assessment;
    return (
      <div className="review-tab">
        <span className="eyebrow">Earlier coach</span>
        <p>{a.summary}</p>
        <ul className="plain-list">
          {a.concepts.map((c) => (
            <li key={c.concept_id}>
              <strong>{conceptName(c.concept_id)}</strong>{" "}
              <span className={`status-badge ${c.status}`}>
                {conceptLabels[c.status]}
              </span>
            </li>
          ))}
        </ul>
        {onRefresh && <Rereview attempt={attempt} onRefresh={onRefresh} />}
      </div>
    );
  }
  if (isTooShort(attempt))
    return (
      <div className="review-tab">
        {attempt.number === 1 ? (
          <>
            <p>
              No substantive explanation was recorded. Record again when you’re
              ready.
            </p>
            {onRecordAgain && (
              <button className="button primary small" onClick={onRecordAgain}>
                Record again
              </button>
            )}
          </>
        ) : (
          <p>No substantive explanation was recorded for this attempt.</p>
        )}
        {history}
      </div>
    );
  if (!review)
    return (
      <div className="review-tab">
        <p className="muted">
          {processing(attempt) || attempt.analysis?.passes
            ? "The review appears here once the coach has finished."
            : "The review isn’t available for this attempt."}
        </p>
        {technical && (
          <TechnicalDetails
            attempt={attempt}
            technical={technical}
            onRef={onRef}
          />
        )}
        {history}
      </div>
    );

  const scores = orderScores(review.scores);
  const shown = scores.find((s) => s.name === open);
  return (
    <div className="review-tab">
      <div className="score-row">
        {scores.map((s) => (
          <button
            key={s.name}
            type="button"
            className={`score-chip ${CORE_SCORES.includes(s.name) ? "" : "focus"} ${open === s.name ? "open" : ""}`}
            title={s.reason}
            aria-expanded={open === s.name}
            onClick={() => setOpen(open === s.name ? null : s.name)}
          >
            {s.name} {scoreText(s.score)}
          </button>
        ))}
      </div>
      {shown && (
        <p className="score-reason small">
          <strong>{shown.name}:</strong> {shown.reason}
        </p>
      )}
      <p className="small muted">Coaching estimates, not measurements.</p>
      {review.comparison && (
        <div className="score-changes">
          <h3>Since attempt 1</h3>
          <ul className="plain-list">
            {review.comparison.changes.map((c) => (
              <li key={c.name}>
                {c.name} {scoreText(c.before)} → {scoreText(c.after)}
              </li>
            ))}
          </ul>
          <p>{review.comparison.what_changed}</p>
        </div>
      )}
      <h3>Key points</h3>
      <ol className="key-points">
        {review.key_points.map((p, i) => (
          <li key={i}>
            {p.text}{" "}
            <LineRefs attempt={attempt} ids={p.line_ids} onRef={onRef} />
          </li>
        ))}
      </ol>
      <h3>{attempt.number === 1 ? "For attempt 2" : "For next time"}</h3>
      <ul className="checklist">
        {review.checklist.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {warning && <p className="small muted">{warning}</p>}
      {previous && !review.comparison && reviewStructure(previous) && (
        <p className="small muted">
          No score comparison with attempt 1 was written.
        </p>
      )}
      {technical && (
        <details className="review-details">
          <summary>Technical details</summary>
          <TechnicalDetails
            attempt={attempt}
            technical={technical}
            onRef={onRef}
          />
        </details>
      )}
      {history}
    </div>
  );
}
