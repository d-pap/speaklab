import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, errorText, put } from "./api";
import { ErrorNotice } from "./components";
import type { PassSettings } from "./types";

const PASS_LABELS: [keyof PassSettings, string][] = [
  ["technical", "Technical review"],
  ["communication", "Communication review"],
  ["writer", "Review writer"],
  ["chat", "Chat"],
  ["memory", "Coach notes"],
];

// The ranges PUT /api/settings/passes accepts (llm.NUM_CTX_RANGE, llm.NUM_PREDICT_RANGE).
const LIMITS = {
  num_ctx: {
    label: "context size",
    name: "Context size",
    min: 4096,
    max: 32768,
  },
  num_predict: {
    label: "output limit",
    name: "Output limit",
    min: 512,
    max: 4096,
  },
} as const;
type Limit = keyof typeof LIMITS;
const validLimit = (field: Limit, value: number) =>
  Number.isInteger(value) &&
  value >= LIMITS[field].min &&
  value <= LIMITS[field].max;

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
  const [passes, setPasses] = useState<PassSettings | null>(null);
  const [passDraft, setPassDraft] = useState<PassSettings | null>(null);
  const [passSaving, setPassSaving] = useState(false);
  const [passSaved, setPassSaved] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await api<Catalog>("/models");
      setCatalog(next);
      setDraft(next.selected);
      const p = await api<PassSettings>("/settings/passes");
      setPasses(p);
      setPassDraft(p);
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
      const next = await api<PassSettings>("/settings/passes");
      setPasses(next);
      setPassDraft(next);
      setSaved(true);
      onSaved(result.selected);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }
  async function savePasses() {
    if (!passDraft) return;
    setPassSaving(true);
    setPassSaved(false);
    setError("");
    try {
      const next = await put<PassSettings>("/settings/passes", {
        passes: passDraft,
      });
      setPasses(next);
      setPassDraft(next);
      setPassSaved(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPassSaving(false);
    }
  }
  const passesChanged =
    !!passes &&
    !!passDraft &&
    PASS_LABELS.some(
      ([k]) =>
        passes[k].model !== passDraft[k].model ||
        passes[k].num_ctx !== passDraft[k].num_ctx ||
        passes[k].num_predict !== passDraft[k].num_predict,
    );
  const invalidLimits = (Object.keys(LIMITS) as Limit[]).filter(
    (field) =>
      !!passDraft &&
      PASS_LABELS.some(([k]) => !validLimit(field, passDraft[k][field])),
  );
  const choice = catalog?.models.find((m) => m.name === draft);
  return (
    <div className="model-picker">
      <label htmlFor="local-model">Model for feedback & coaching</label>
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
      {passDraft && (
        <details className="pass-models">
          <summary>Advanced: model per step</summary>
          {PASS_LABELS.map(([key, label]) => (
            <div className="pass-row" key={key}>
              <label htmlFor={`pass-${key}`}>{label}</label>
              <select
                id={`pass-${key}`}
                value={passDraft[key].model}
                disabled={loading || passSaving || !catalog?.models.length}
                onChange={(e) => {
                  setPassSaved(false);
                  setPassDraft({
                    ...passDraft,
                    [key]: { ...passDraft[key], model: e.target.value },
                  });
                }}
              >
                {!catalog?.models.some(
                  (m) => m.name === passDraft[key].model,
                ) && (
                  <option value={passDraft[key].model}>
                    {passDraft[key].model} · not installed
                  </option>
                )}
                {catalog?.models.map((m) => (
                  <option key={m.name} value={m.name} disabled={!m.selectable}>
                    {m.name}
                    {!m.selectable ? " · unavailable" : ""}
                  </option>
                ))}
              </select>
              <div className="pass-limits">
                {(Object.keys(LIMITS) as Limit[]).map((field) => (
                  <label key={field}>
                    <span className="small muted">{LIMITS[field].name}</span>
                    <input
                      type="number"
                      inputMode="numeric"
                      aria-label={`${label} ${LIMITS[field].label}`}
                      min={LIMITS[field].min}
                      max={LIMITS[field].max}
                      step={field === "num_ctx" ? 1024 : 256}
                      value={
                        Number.isNaN(passDraft[key][field])
                          ? ""
                          : passDraft[key][field]
                      }
                      aria-invalid={!validLimit(field, passDraft[key][field])}
                      disabled={loading || passSaving}
                      onChange={(e) => {
                        setPassSaved(false);
                        setPassDraft({
                          ...passDraft,
                          [key]: {
                            ...passDraft[key],
                            [field]: e.target.valueAsNumber,
                          },
                        });
                      }}
                    />
                  </label>
                ))}
              </div>
            </div>
          ))}
          <p className="small muted">
            A step that says its prompt is too long needs a larger context size.
            Larger sizes use more memory on the connected computer.
          </p>
          {invalidLimits.map((field) => (
            <p key={field} className="small word-count over">
              {LIMITS[field].name}: {LIMITS[field].min} to {LIMITS[field].max}
              {field === "num_ctx" ? " tokens." : " tokens per reply."}
            </p>
          ))}
          <div className="actions">
            <button
              className="button primary small"
              disabled={
                loading ||
                passSaving ||
                !passesChanged ||
                invalidLimits.length > 0
              }
              onClick={() => void savePasses()}
            >
              {passSaving ? "Saving…" : "Save step models"}
            </button>
          </div>
          {passSaved && (
            <p role="status" className="small">
              Step models saved.
            </p>
          )}
        </details>
      )}
      {saved && (
        <p role="status" className="small">
          Model saved. New reviews and coach replies will use{" "}
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
        reviews keep their original model. Finish active analysis or coach
        replies before switching.
      </p>
    </div>
  );
}
