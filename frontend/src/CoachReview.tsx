import { Clock3 } from "lucide-react";
import { renderMarkdownLines, splitLines } from "./markdown";
import { lineLabel } from "./markers";
import type { Attempt, MessagePart, SectionTiming } from "./types";

type Section = { title: string; lines: MessagePart[][] };
type Jump = (id: string) => void;

// Match only whole, known headings. Prose, inline quotes and other Markdown
// stay intact, including when a writer uses entirely different headings.
const TITLES = new Map([
  ["your read", "Your read"],
  ["three priorities", "Three priorities"],
  ["where the time went", "Where the time went"],
  ["moments", "Moments"],
  ["in the moment", "Moments"],
  ["key moments", "Moments"],
  [
    "technical corrections and what to learn",
    "Technical corrections and what to learn",
  ],
  ["a strong answer", "A strong answer"],
  ["next time", "Next time"],
]);
function sections(parts: MessagePart[]): Section[] {
  const result: Section[] = [{ title: "", lines: [] }];
  for (const line of splitLines(parts)) {
    const first = line[0];
    const label =
      line.length === 1 && first.type === "text"
        ? first.text
            .trim()
            .replace(/^#{1,6}\s+/, "")
            .replace(/\*\*/g, "")
            .replace(/^\d+[.)]\s*/, "")
            .replace(/:$/, "")
            .trim()
            .toLowerCase()
        : "";
    const title = TITLES.get(label);
    if (title) result.push({ title, lines: [] });
    else result[result.length - 1].lines.push(line);
  }
  return result;
}

function TimingChart({ rows }: { rows: SectionTiming[] }) {
  return (
    <figure className="section-timing" aria-label="Time spent per section">
      {rows.map((row) => (
        <div className="timing-row" key={row.label}>
          <span>{row.label}</span>
          <span className="timing-value">
            {row.seconds}s <span>· {row.percent}%</span>
          </span>
          <div className="timing-track" aria-hidden="true">
            <div style={{ width: `${row.percent}%` }} />
          </div>
        </div>
      ))}
    </figure>
  );
}

export function CoachReview({
  attempt,
  parts,
  onRef,
}: {
  attempt: Attempt;
  parts: MessagePart[];
  onRef: Jump;
}) {
  const analysis = attempt.analysis;
  const rows = analysis?.timing ?? [];
  const moments = (analysis?.communication?.points ?? []).flatMap((point) => {
    const line = attempt.lines?.find((l) => l.id === point.line_id);
    return line ? [{ point, line }] : [];
  });
  const groups = sections(parts);
  // Old reviews and model changes may omit the expected headings. The saved
  // evidence still gets its own section; never infer a time from prose.
  for (const [title, available] of [
    ["Where the time went", rows.length],
    ["Moments", moments.length],
  ] as const) {
    if (available && !groups.some((g) => g.title === title)) {
      const nextTime = groups.findIndex((g) => g.title === "Next time");
      groups.splice(nextTime < 0 ? groups.length : nextTime, 0, {
        title,
        lines: [],
      });
    }
  }

  function momentCard(
    { point, line }: (typeof moments)[number],
    index: number,
  ) {
    return (
      <article key={index} className="review-moment">
        <header>
          <button
            type="button"
            className="moment-link"
            onClick={() => onRef(line.id)}
            title="Open this transcript line"
          >
            <Clock3 size={14} aria-hidden="true" />
            {lineLabel(line.id, line.start)}
          </button>
          <span>
            {point.kind === "strength" ? "What worked" : "What to change"}
          </span>
        </header>
        <blockquote>{line.text}</blockquote>
        <p>{point.observation}</p>
        {point.rewrite && (
          <p className="moment-rewrite">
            <strong>Try saying</strong> {point.rewrite}
          </p>
        )}
      </article>
    );
  }

  return groups.map((group, index) => {
    const prose = renderMarkdownLines(group.lines, onRef);
    if (!group.title && !prose.length) return null;
    const timing = group.title === "Where the time went" && rows.length > 0;
    const cited = group.title === "Moments" && moments.length > 0;
    const longIntro =
      !group.title &&
      (rows.length || moments.length) &&
      group.lines
        .flat()
        .reduce((n, p) => n + (p.type === "text" ? p.text.length : 0), 0) >
        1600;
    if (group.title === "A strong answer" || longIntro) {
      return (
        <details key={index} className="review-section review-reading">
          <summary>{group.title || "Read the full review"}</summary>
          {prose}
        </details>
      );
    }
    return (
      <div className="review-section" key={index}>
        {group.title && <h4 className="md-heading">{group.title}</h4>}
        {timing && <TimingChart rows={rows} />}
        {cited && (
          <>
            {moments.slice(0, 2).map(momentCard)}
            {moments.length > 2 && (
              <details className="review-reading">
                <summary>
                  {moments.length - 2} more{" "}
                  {moments.length === 3 ? "moment" : "moments"}
                </summary>
                {moments.slice(2).map(momentCard)}
              </details>
            )}
          </>
        )}
        {(timing || cited) && prose.length > 0 ? (
          <details className="review-reading">
            <summary>Coach’s commentary</summary>
            {prose}
          </details>
        ) : (
          prose
        )}
      </div>
    );
  });
}
