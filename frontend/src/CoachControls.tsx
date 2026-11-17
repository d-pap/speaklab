import { useCallback, useEffect, useId, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, errorText, post, put } from "./api";
import { ErrorNotice } from "./components";
import { Rereview } from "./Insights";
import type { Catalog } from "./ModelPicker";
import type { Attempt, PassSettings } from "./types";

/** The same app-wide model selection as Settings, close to the conversation it affects. */
export function CoachControls({
  attempt,
  disabled,
  onBusyChange,
  onRefresh,
}: {
  attempt: Attempt;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onRefresh: () => Promise<void>;
}) {
  const id = useId();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [passes, setPasses] = useState<PassSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [models, steps] = await Promise.all([
        api<Catalog>("/models"),
        api<PassSettings>("/settings/passes"),
      ]);
      setCatalog(models);
      setPasses(steps);
      setError("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function choose(model: string) {
    if (!model || working || disabled) return;
    setWorking(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      await put("/settings/model", { model });
      setPasses((p) =>
        p
          ? (Object.fromEntries(
              Object.entries(p).map(([key, value]) => [
                key,
                { ...value, model },
              ]),
            ) as PassSettings)
          : null,
      );
      setNotice(`New reviews and replies will use ${model}.`);
      window.dispatchEvent(new Event("speaklab-model-changed"));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setWorking(false);
      onBusyChange(false);
    }
  }

  async function regenerate() {
    if (working || disabled) return;
    setWorking(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      await post(`/attempts/${attempt.id}/rereview`);
      setNotice("Review requested. The previous version is saved.");
      await onRefresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setWorking(false);
      onBusyChange(false);
    }
  }

  const models = passes ? Object.values(passes).map((p) => p.model) : [];
  const uniform = models.length > 0 && models.every((m) => m === models[0]);
  const selected = uniform ? models[0] : "";
  return (
    <div className="coach-controls" role="group" aria-label="Coach controls">
      <div className="coach-control-row">
        <label className="sr-only" htmlFor={id}>
          Coach model
        </label>
        <select
          id={id}
          value={selected}
          disabled={disabled || working || loading || !catalog?.models.length}
          onChange={(e) => void choose(e.target.value)}
        >
          {!uniform && (
            <option value="" disabled>
              {loading
                ? "Loading models…"
                : passes
                  ? "Custom step models"
                  : "Models unavailable"}
            </option>
          )}
          {uniform && !catalog?.models.some((m) => m.name === selected) && (
            <option value={selected}>{selected} · not installed</option>
          )}
          {catalog?.models.map((m) => (
            <option key={m.name} value={m.name} disabled={!m.selectable}>
              {m.name}
              {!m.selectable ? " · unavailable" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="icon-button"
          aria-label="Refresh coach models"
          disabled={disabled || working || loading}
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} />
        </button>
        <button
          type="button"
          className="button secondary small"
          disabled={disabled || working}
          onClick={() => void regenerate()}
        >
          <RefreshCw size={14} /> Regenerate review
        </button>
      </div>
      <p className="small muted">
        Model changes apply to new reviews and replies across SpeakLab.{" "}
        <a href="#/settings">Per-step settings</a>
      </p>
      {!uniform && passes && (
        <p className="small muted">
          Chat uses {passes.chat.model}; review models are set per step.
        </p>
      )}
      <p className="small muted">
        Regenerate reruns the full review and saves the previous version. Your
        chat stays here.
      </p>
      <Rereview
        key={attempt.analysis?.passes.writer.status ?? attempt.status}
        attempt={attempt}
        onRefresh={onRefresh}
        historyOnly
      />
      {notice && (
        <p className="small muted" role="status">
          {notice}
        </p>
      )}
      {error && (
        <ErrorNotice
          message={error}
          retry={() => {
            void onRefresh()
              .then(refresh)
              .catch((e) => setError(errorText(e)));
          }}
        />
      )}
    </div>
  );
}
