import { createElement, type ReactNode } from "react";
import { timeLabel } from "./api";
import type { MessagePart } from "./types";

/** The label for a line link: its start time, or "line N" for an untimed transcript. */
export const lineLabel = (lineId: string, start: number | null) =>
  start != null ? timeLabel(start) : `line ${lineId.replace(/^L/, "")}`;

/** A line link as a button that calls onRef, followed by its quote when it has one. */
export function renderRef(
  part: Extract<MessagePart, { type: "ref" }>,
  key: string,
  onRef: (lineId: string) => void,
): ReactNode[] {
  const button = createElement(
    "button",
    {
      key,
      type: "button",
      className: "time-ref",
      onClick: () => onRef(part.line_id),
    },
    lineLabel(part.line_id, part.start),
  );
  return part.quote ? [button, ` “${part.quote}”`] : [button];
}

/** Render resolved message parts; line links become buttons that call onRef. */
export function renderParts(
  parts: MessagePart[],
  onRef: (lineId: string) => void,
): ReactNode[] {
  return parts.flatMap((part, i): ReactNode[] =>
    part.type === "text" ? [part.text] : renderRef(part, `ref-${i}`, onRef),
  );
}

/** While a reply streams, show line markers (complete or still arriving) as "…". */
export const stripMarkersForStreaming = (text: string) =>
  text
    .replace(/\[\[L\d+(?::"[^"]*")?\]\]/g, "…")
    .replace(/\[\[[^\]]*\]?$/, "…")
    .replace(/\[$/, "");
