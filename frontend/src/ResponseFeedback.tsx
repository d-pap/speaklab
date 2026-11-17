import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { errorText, put } from "./api";
import { ErrorNotice } from "./components";
import type { Message, ResponseFeedback as Feedback } from "./types";

const REASONS = [
  ["missed_insight", "Missed something important"],
  ["wrong_diagnosis", "Wrong diagnosis or reasoning"],
  ["incorrect", "Technically incorrect"],
  ["teaching", "Explanation or teaching"],
  ["too_vague", "Too vague"],
  ["too_long", "Too much detail"],
  ["style", "Tone or style"],
  ["other", "Something else"],
];

export function ResponseFeedback({ message }: { message: Message }) {
  const [saved, setSaved] = useState(message.feedback ?? null);
  const [expanded, setExpanded] = useState(false);
  const [reason, setReason] = useState(saved?.reason ?? "");
  const [comment, setComment] = useState(saved?.comment ?? "");
  const [preferred, setPreferred] = useState(saved?.preferred_response ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const prefix = `feedback-${message.id}`;

  async function save(rating: 1 | -1 | null, details = false) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await put<{ feedback: Feedback | null }>(
        `/messages/${message.id}/feedback`,
        {
          rating,
          reason: details ? reason || null : (saved?.reason ?? null),
          comment: details ? comment : (saved?.comment ?? ""),
          preferred_response: details
            ? preferred
            : (saved?.preferred_response ?? ""),
        },
      );
      setSaved(response.feedback);
      setNotice(
        rating === null ? "Feedback removed" : "Feedback saved locally",
      );
      if (rating === null) {
        setExpanded(false);
        setReason("");
        setComment("");
        setPreferred("");
      } else if (details) setExpanded(false);
      else if (rating === -1) setExpanded(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="response-feedback"
      role="group"
      aria-label="Feedback on coach response"
    >
      <div className="feedback-actions">
        <button
          type="button"
          className="feedback-vote"
          aria-label="Helpful"
          aria-pressed={saved?.rating === 1}
          disabled={busy}
          onClick={() => void save(saved?.rating === 1 ? null : 1)}
        >
          <ThumbsUp size={15} />
        </button>
        <button
          type="button"
          className="feedback-vote"
          aria-label="Not helpful"
          aria-pressed={saved?.rating === -1}
          disabled={busy}
          onClick={() => void save(saved?.rating === -1 ? null : -1)}
        >
          <ThumbsDown size={15} />
        </button>
        {saved && (
          <button
            type="button"
            className="small muted"
            aria-expanded={expanded}
            aria-controls={`${prefix}-details`}
            disabled={busy}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Hide details" : "Add or edit details"}
          </button>
        )}
      </div>
      {expanded && saved && (
        <form
          id={`${prefix}-details`}
          className="feedback-details"
          onSubmit={(e) => {
            e.preventDefault();
            void save(saved.rating, true);
          }}
        >
          <label htmlFor={`${prefix}-reason`}>What stood out? (optional)</label>
          <select
            id={`${prefix}-reason`}
            value={reason}
            disabled={busy}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="">Choose a reason</option>
            {REASONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <label htmlFor={`${prefix}-comment`}>
            Tell the coach what worked or missed the mark (optional)
          </label>
          <textarea
            id={`${prefix}-comment`}
            rows={2}
            maxLength={4000}
            value={comment}
            disabled={busy}
            onChange={(e) => setComment(e.target.value)}
          />
          <label htmlFor={`${prefix}-preferred`}>
            What would a better response say? (optional)
          </label>
          <textarea
            id={`${prefix}-preferred`}
            rows={3}
            maxLength={20000}
            value={preferred}
            disabled={busy}
            onChange={(e) => setPreferred(e.target.value)}
          />
          <p className="small muted">
            Saved for improving coaching. The coach won’t reply to this
            feedback.
          </p>
          <button
            className="button secondary small"
            disabled={busy}
            type="submit"
          >
            Save details
          </button>
        </form>
      )}
      <span className="small muted" role="status">
        {notice}
      </span>
      {error && <ErrorNotice message={error} />}
    </div>
  );
}
