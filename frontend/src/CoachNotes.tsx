import { useCallback, useEffect, useState } from "react";
import { api, dateLabel, errorText, post, put } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { CoachNotes as Notes } from "./types";

const LIMIT = 400;
const words = (text: string) => text.trim().split(/\s+/).filter(Boolean).length;

export function CoachNotes() {
  const [notes, setNotes] = useState<Notes | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      setNotes(await api<Notes>("/coach-notes"));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<Notes>, done?: () => void) {
    setBusy(true);
    setError("");
    try {
      setNotes(await action());
      done?.();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const count = draft === null ? 0 : words(draft);
  const over = count > LIMIT;
  return (
    <section className="panel coach-notes" aria-labelledby="coach-notes-h">
      <div className="panel-heading">
        <h2 id="coach-notes-h">What your coach remembers</h2>
      </div>
      {!notes && !error && <Loading />}
      {notes && draft === null && (
        <>
          <p className="coach-notes-text">
            {notes.current.content ||
              "Nothing yet. Notes appear after your first review."}
          </p>
          <div className="actions">
            <button
              className="button small"
              disabled={busy}
              onClick={() => setDraft(notes.current.content)}
            >
              Edit
            </button>
          </div>
        </>
      )}
      {notes && draft !== null && (
        <>
          <textarea
            aria-label="Coach notes"
            rows={10}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p
            data-testid="word-count"
            className={`small word-count ${over ? "over" : "muted"}`}
          >
            {count} / {LIMIT} words
          </p>
          <div className="actions">
            <button
              className="button primary small"
              disabled={busy || over}
              onClick={() =>
                void run(
                  () => put<Notes>("/coach-notes", { content: draft }),
                  () => setDraft(null),
                )
              }
            >
              Save
            </button>
            <button
              className="button small"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              Cancel
            </button>
          </div>
        </>
      )}
      {error && <ErrorNotice message={error} retry={() => void load()} />}
      {notes && notes.versions.length > 0 && (
        <details className="note-versions">
          <summary>Previous versions</summary>
          <ul>
            {notes.versions.map((v) => (
              <li key={v.id}>
                <span>
                  {dateLabel(v.created_at)} · {v.source}
                </span>
                <button
                  className="text-button"
                  disabled={busy || draft !== null}
                  onClick={() =>
                    void run(() => post<Notes>(`/coach-notes/${v.id}/restore`))
                  }
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
