import type { ReactNode } from "react";
import { renderRef } from "./markers";
import type { MessagePart } from "./types";

/*
 * A minimal Markdown renderer for coach prose: headings, **bold**, bullet and numbered
 * lists, and paragraphs. It builds React nodes from text, so model text never becomes
 * HTML: a tag in a reply shows as the characters typed. Line links (ref parts) render as
 * they do everywhere else and may sit anywhere in a line.
 */

type Line = MessagePart[];
type Block =
  | { kind: "heading"; line: Line }
  | { kind: "p"; lines: Line[] }
  | { kind: "ul"; items: Line[] }
  | { kind: "ol"; start: number; items: Line[] };

const HEADING = /^\s{0,3}#{1,6}\s+/;
const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*(\d{1,3})[.)]\s+/;

function splitLines(parts: MessagePart[]): Line[] {
  const lines: Line[] = [[]];
  for (const part of parts) {
    if (part.type !== "text") {
      lines[lines.length - 1].push(part);
      continue;
    }
    part.text.split("\n").forEach((piece, i) => {
      if (i > 0) lines.push([]);
      if (piece) lines[lines.length - 1].push({ type: "text", text: piece });
    });
  }
  return lines;
}

/** The line with its leading marker removed, when its first part is text matching pattern. */
function strip(line: Line, pattern: RegExp): [Line, RegExpMatchArray] | null {
  const first = line[0];
  if (!first || first.type !== "text") return null;
  const match = first.text.match(pattern);
  if (!match) return null;
  const text = first.text.slice(match[0].length);
  return [[...(text ? [{ ...first, text }] : []), ...line.slice(1)], match];
}

const blank = (line: Line) =>
  line.every((part) => part.type === "text" && !part.text.trim());

function blocks(lines: Line[]): Block[] {
  const result: Block[] = [];
  for (const line of lines) {
    const last = result[result.length - 1];
    if (blank(line)) {
      result.push({ kind: "p", lines: [] }); // a paragraph break
      continue;
    }
    const heading = strip(line, HEADING);
    const bullet = heading ? null : strip(line, BULLET);
    const numbered = heading || bullet ? null : strip(line, NUMBERED);
    if (heading) result.push({ kind: "heading", line: heading[0] });
    else if (bullet) {
      if (last?.kind === "ul") last.items.push(bullet[0]);
      else result.push({ kind: "ul", items: [bullet[0]] });
    } else if (numbered) {
      if (last?.kind === "ol") last.items.push(numbered[0]);
      else
        result.push({
          kind: "ol",
          start: Number(numbered[1][1]),
          items: [numbered[0]],
        });
    } else if (last?.kind === "p") last.lines.push(line);
    else result.push({ kind: "p", lines: [line] });
  }
  return result.filter((b) => b.kind !== "p" || b.lines.length > 0);
}

/** Text and line links, with **bold** spans; an unpaired ** stays as typed. */
function inline(
  line: Line,
  key: string,
  onRef: (lineId: string) => void,
): ReactNode[] {
  const markers = line.reduce(
    (n, part) =>
      n + (part.type === "text" ? part.text.split("**").length - 1 : 0),
    0,
  );
  const usable = markers - (markers % 2);
  let seen = 0;
  let bold = false;
  const out: ReactNode[] = [];
  let strong: ReactNode[] = [];
  const emit = (node: ReactNode) => (bold ? strong : out).push(node);
  line.forEach((part, i) => {
    if (part.type !== "text") {
      emit(renderRef(part, `${key}-ref-${i}`, onRef));
      return;
    }
    part.text.split("**").forEach((piece, j) => {
      if (j > 0) {
        if (seen < usable) {
          seen++;
          if (bold) {
            out.push(<strong key={`${key}-b-${i}-${j}`}>{strong}</strong>);
            strong = [];
          }
          bold = !bold;
        } else emit("**");
      }
      if (piece) emit(piece);
    });
  });
  return out;
}

export function renderMarkdown(
  parts: MessagePart[],
  onRef: (lineId: string) => void,
): ReactNode[] {
  return blocks(splitLines(parts)).map((block, b) => {
    const key = `md-${b}`;
    if (block.kind === "heading")
      return (
        <h4 key={key} className="md-heading">
          {inline(block.line, key, onRef)}
        </h4>
      );
    if (block.kind === "ul" || block.kind === "ol") {
      const items = block.items.map((item, i) => (
        <li key={`${key}-${i}`}>{inline(item, `${key}-${i}`, onRef)}</li>
      ));
      return block.kind === "ul" ? (
        <ul key={key}>{items}</ul>
      ) : (
        <ol key={key} start={block.start}>
          {items}
        </ol>
      );
    }
    return (
      <p key={key}>
        {block.lines.flatMap((line, i) => [
          ...(i > 0 ? [<br key={`${key}-br-${i}`} />] : []),
          ...inline(line, `${key}-${i}`, onRef),
        ])}
      </p>
    );
  });
}
