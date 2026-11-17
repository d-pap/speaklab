import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Mic } from "lucide-react";
import { api, ApiError, dateLabel, errorText } from "./api";
import { Empty, ErrorNotice, Loading } from "./components";
import { NewAttempt } from "./NewAttempt";
import { reviewing } from "./Practice";
import { ReviewPage } from "./ReviewPage";
import type { Attempt, Thread } from "./types";

/** One topic's practice thread (#/topic/<id>). Every attempt stays reachable through the
 * attempt pills; the latest opens by default. An unpractised topic opens straight on the
 * recording screen, and #/topic/<id>/new records the next attempt when one is open. */
export function TopicPage({
  topicId,
  attemptNumber,
  wantsNew,
  navigate,
  onDirty,
}: {
  topicId: string;
  attemptNumber: number | null;
  wantsNew: boolean;
  navigate: (page: string) => void;
  onDirty: (value: boolean) => void;
}) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  // The route the thread was last fetched for; a stale thread never drives a redirect.
  const [fetchedFor, setFetchedFor] = useState("");
  const routeKey = `${attemptNumber}|${wantsNew}`;
  // A response for a topic the learner has since left is dropped, never shown.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const base = `topic/${encodeURIComponent(topicId)}`;
  const load = useCallback(async () => {
    const next = await api<Thread>(
      `/topics/${encodeURIComponent(topicId)}/thread`,
    );
    if (!alive.current) return;
    setThread(next);
    setError("");
  }, [topicId]);
  const fail = useCallback((e: unknown) => {
    if (!alive.current) return;
    if (e instanceof ApiError && e.status === 404) setMissing(true);
    else setError(errorText(e));
  }, []);
  // Every move within the topic (a pill, back from the recorder) refreshes the thread.
  useEffect(() => {
    setError("");
    void load()
      .then(() => {
        if (alive.current) setFetchedFor(routeKey);
      })
      .catch(fail);
  }, [load, fail, routeKey]);
  // Poll while analysis runs or a review is on its way.
  const running = thread?.attempts.some(reviewing);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load().catch(fail), 2500);
    return () => clearInterval(timer);
  }, [running, load, fail]);

  // A direct link to /new while no attempt may open drops the suffix, so the button works later.
  // Not after a save: that move navigates to the new attempt itself.
  const justSaved = useRef(false);
  useEffect(() => {
    if (!wantsNew) justSaved.current = false;
  }, [wantsNew]);
  const redirectNew = !!thread && fetchedFor === routeKey && wantsNew && !thread.recording.can_record;
  useEffect(() => {
    if (redirectNew && !justSaved.current) location.replace(`#/${base}`);
  }, [redirectNew, base]);

  if (missing)
    return (
      <Empty title="That topic isn’t here.">
        <button className="text-button" onClick={() => navigate("today")}>
          Return to your practice
        </button>
      </Empty>
    );
  if (!thread)
    return error ? (
      <ErrorNotice message={error} retry={() => void load().catch(fail)} />
    ) : (
      <Loading />
    );

  const latest = thread.attempts.at(-1);
  const { recording } = thread;
  if (!latest || (wantsNew && recording.can_record)) {
    const saved = async (attempt: Attempt) => {
      justSaved.current = true;
      await load().catch(() => {});
      navigate(`${base}?attempt=${attempt.number}`);
    };
    return (
      <NewAttempt
        thread={thread}
        onCancel={() => navigate(latest ? base : "today")}
        onSaved={(attempt) => void saved(attempt)}
        onDirty={onDirty}
      />
    );
  }
  const selected =
    thread.attempts.find((a) => a.number === attemptNumber) ?? latest;
  const recordNext = () => navigate(`${base}/new`);
  return (
    <div className="topic-page">
      {error && <ErrorNotice message={error} />}
      <div className="session-top">
        <button className="text-button muted" onClick={() => navigate("today")}>
          <ArrowLeft size={15} /> Back to today
        </button>
        <span className="small muted">
          Attempt {selected.number} · {dateLabel(selected.created_at)}
        </span>
      </div>
      <header className="topic-heading">
        <span className="eyebrow">{thread.topic.category}</span>
        <h1>{thread.topic.title}</h1>
        {selected.prompt && <p>{selected.prompt}</p>}
      </header>
      <div className="topic-toolbar">
        <div
          className="attempt-switch"
          role="group"
          aria-label="Choose an attempt"
        >
          {thread.attempts.map((a) => (
            <button
              key={a.number}
              aria-pressed={a.number === selected.number}
              className={a.number === selected.number ? "on" : ""}
              title={dateLabel(a.created_at)}
              onClick={() => navigate(`${base}?attempt=${a.number}`)}
            >
              Attempt {a.number}
            </button>
          ))}
        </div>
        {recording.can_record ? (
          <button className="button primary small" onClick={recordNext}>
            <Mic size={15} /> New attempt
          </button>
        ) : (
          <span className="small muted">{recording.reason}</span>
        )}
      </div>
      <ReviewPage
        key={selected.number}
        thread={thread}
        attemptNumber={selected.number}
        onRefresh={load}
        onRecordAgain={
          recording.replace_number === selected.number ? recordNext : undefined
        }
      />
    </div>
  );
}
