import { useCallback, useState } from "react";
import { X } from "lucide-react";
import { api } from "./api";
import { Recorder } from "./Recorder";
import type { Attempt, Thread } from "./types";

const STYLES = [
  "Conversational",
  "Thoughtful teacher",
  "Concise interview",
  "Animated storyteller",
];
const DURATIONS = [120, 180, 240, 300];
const FIRST_KIND = "Concept explanation";
const SAVED = "speaklab-first-attempt";

/** The speaking time and style last chosen for a first attempt. The question type is per topic
 * and never remembered. Storage may be unavailable; the defaults apply then. */
function savedSettings(): { duration: number; style: string } {
  const fallback = { duration: 120, style: "Conversational" };
  try {
    const value = JSON.parse(localStorage.getItem(SAVED) ?? "{}");
    return {
      duration: DURATIONS.includes(value.duration)
        ? value.duration
        : fallback.duration,
      style: STYLES.includes(value.style) ? value.style : fallback.style,
    };
  } catch {
    return fallback;
  }
}
function saveSettings(duration: number, style: string) {
  try {
    localStorage.setItem(SAVED, JSON.stringify({ duration, style }));
  } catch {
    /* The choice still applies to this recording. */
  }
}

/** The recording screen for a topic's next attempt, and the first screen of an unpractised
 * topic. It shows the topic, the question and the latest "For next time" checklist, and never
 * past reviews, chat or references. */
export function NewAttempt({
  thread,
  onCancel,
  onSaved,
  onDirty,
}: {
  thread: Thread;
  onCancel: () => void;
  onSaved: (attempt: Attempt) => void;
  onDirty: (value: boolean) => void;
}) {
  const latest = thread.attempts.at(-1);
  const first = !latest;
  const number = thread.recording.next_number;
  const replacing = thread.recording.replace_number;
  const kinds = Object.keys(thread.prompts);
  // The previous attempt's question type is the default. A retired one (no longer offered)
  // is kept as "the same question" and never sent, so the server carries it over.
  const inherited = latest?.prompt_kind ?? FIRST_KIND;
  const retired = !kinds.includes(inherited);
  const [kind, setKind] = useState(retired ? "" : inherited);
  // Later attempts keep their own; a first attempt starts from the last first-attempt choice.
  const [initial] = useState(() =>
    latest
      ? { duration: latest.target_duration, style: latest.style }
      : savedSettings(),
  );
  const [duration, setDuration] = useState(initial.duration);
  const [style, setStyle] = useState(initial.style);
  const [unsaved, setUnsaved] = useState(false);
  const question = kind
    ? thread.prompts[kind]
    : latest?.prompt || thread.topic.prompt;
  const dirty = useCallback(
    (value: boolean) => {
      setUnsaved(value);
      onDirty(value);
    },
    [onDirty],
  );
  async function upload(audio: Blob) {
    const form = new FormData();
    form.append("file", audio, "recording");
    if (kind && kind !== inherited) form.append("prompt_kind", kind);
    // Later attempts keep their speaking time and style on the server.
    if (first) {
      form.append("style", style);
      form.append("duration", String(duration));
    }
    return api<Attempt>(
      `/topics/${encodeURIComponent(thread.topic.id)}/attempts`,
      {
        method: "POST",
        body: form,
      },
    );
  }
  const checklist = thread.latest_checklist;
  return (
    <Recorder
      number={number}
      duration={duration}
      style={style}
      onUpload={upload}
      onSaved={onSaved}
      onDirty={dirty}
      brief={
        <>
          <div className="session-top">
            <button className="text-button muted" onClick={onCancel}>
              <X size={15} /> Cancel
            </button>
          </div>
          <div className="record-heading">
            <span className="eyebrow">
              ATTEMPT {number}
              {replacing ? "" : first ? " · FROM MEMORY" : " · ON A NEW DAY"}
            </span>
            <h1>{thread.topic.title}</h1>
            <p>{question}</p>
            {replacing && (
              <p className="replace-note">This replaces attempt {replacing}</p>
            )}
          </div>
          {checklist.length > 0 && (
            <section className="day-two" aria-labelledby="next-time-heading">
              <h2 id="next-time-heading">For next time</h2>
              <ul className="checklist">
                {checklist.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          )}
          <div
            className={`practice-options attempt-options ${first ? "" : "single"}`}
          >
            <label>
              {first ? "Question type" : "Try a different angle"}
              <select
                value={kind}
                disabled={unsaved}
                onChange={(e) => setKind(e.target.value)}
              >
                {retired && (
                  <option value="">Same question as last time</option>
                )}
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            {first && (
              <>
                <label>
                  Speaking time
                  <select
                    value={duration}
                    disabled={unsaved}
                    onChange={(e) => {
                      setDuration(Number(e.target.value));
                      saveSettings(Number(e.target.value), style);
                    }}
                  >
                    {DURATIONS.map((d) => (
                      <option key={d} value={d}>
                        {d / 60} minutes
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Delivery intention
                  <select
                    value={style}
                    disabled={unsaved}
                    onChange={(e) => {
                      setStyle(e.target.value);
                      saveSettings(duration, e.target.value);
                    }}
                  >
                    {STYLES.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>
        </>
      }
    />
  );
}
