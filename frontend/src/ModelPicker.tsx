import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, errorText, put } from "./api";
import { ErrorNotice } from "./components";

type InstalledModel = {
  name: string;
  size_bytes: number;
  parameters: string;
  quantization: string;
  selectable: boolean;
  reason: string | null;
};
type Catalog = { selected: string; models: InstalledModel[] };

export function ModelPicker({ onSaved }: { onSaved: (model: string) => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await api<Catalog>("/models");
      setCatalog(next);
      setDraft(next.selected);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  async function save() {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const result = await put<{ selected: string }>("/settings/model", {
        model: draft,
      });
      setCatalog((c) => (c ? { ...c, selected: result.selected } : c));
      setSaved(true);
      onSaved(result.selected);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }
  const choice = catalog?.models.find((m) => m.name === draft);
  return (
    <div className="model-picker">
      <label htmlFor="local-model">Model for feedback & tutoring</label>
      <select
        id="local-model"
        value={draft}
        disabled={loading || saving || !catalog?.models.length}
        onChange={(e) => {
          setDraft(e.target.value);
          setSaved(false);
        }}
      >
        {!catalog?.models.some((m) => m.name === draft) && (
          <option value={draft}>
            {draft
              ? `${draft} · not installed`
              : loading
                ? "Loading installed models…"
                : "No installed models"}
          </option>
        )}
        {catalog?.models.map((m) => (
          <option key={m.name} value={m.name} disabled={!m.selectable}>
            {m.name}
            {m.parameters ? ` · ${m.parameters}` : ""}
            {!m.selectable ? " · unavailable" : ""}
          </option>
        ))}
      </select>
      {choice && (
        <p className="small muted">
          {choice.parameters} {choice.quantization} ·{" "}
          {(choice.size_bytes / 1e9).toFixed(1)} GB download size
        </p>
      )}
      {choice?.reason && <p className="small muted">{choice.reason}</p>}
      <div className="actions">
        <button
          className="button primary small"
          disabled={
            loading ||
            saving ||
            !choice?.selectable ||
            draft === catalog?.selected
          }
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Use model"}
        </button>
        <button
          className="text-button"
          disabled={loading || saving}
          onClick={() => {
            setSaved(false);
            void refresh();
          }}
        >
          <RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh
          models
        </button>
      </div>
      {saved && (
        <p role="status" className="small">
          Model saved. New feedback and tutor replies will use{" "}
          {catalog?.selected}.
        </p>
      )}
      {error && <ErrorNotice message={error} retry={() => void refresh()} />}
      {!loading && catalog?.models.length === 0 && (
        <p className="small muted">
          Install a chat model in the connected computer’s Ollama service, then
          refresh.
        </p>
      )}
      <p className="small muted">
        Saved on the connected computer, including after a restart. The model
        loads on its next request; the first reply may take longer. Existing
        feedback keeps its original model. Finish active analysis or tutoring
        before switching.
      </p>
    </div>
  );
}
