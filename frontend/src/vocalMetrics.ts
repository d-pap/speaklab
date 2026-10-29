import type { Acoustics } from "./types";

export type VocalWindow = { start: number; end: number; value: number };
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

export function paceWindows(
  metrics: Acoustics | null,
  duration: number,
): VocalWindow[] {
  // Stored rate estimates distribute transcript words over 30-second windows.
  // A short trailing fragment can produce an unstable range, so compare full windows only.
  return (metrics?.rate_track ?? [])
    .filter(
      (p) =>
        finite(p.time) &&
        finite(p.value) &&
        p.time >= 0 &&
        p.value >= 0 &&
        p.time + 30 <= duration + 0.05,
    )
    .map((p) => ({
      start: p.time,
      end: Math.min(p.time + 30, duration),
      value: p.value!,
    }))
    .sort((a, b) => a.start - b.start);
}

export function acousticWindows(
  metrics: Acoustics | null,
  duration: number,
  key: "loudness_range_db" | "pitch_range_semitones",
): VocalWindow[] {
  // These spreads were measured within active/voiced audio, not across silent gaps.
  return (metrics?.delivery_windows ?? [])
    .filter(
      (w) =>
        finite(w.start) &&
        finite(w.end) &&
        finite(w[key]) &&
        w[key]! >= 0 &&
        w.start >= 0 &&
        w.end <= duration + 0.05 &&
        w.end - w.start >= 14.95,
    )
    .map((w) => ({ start: w.start, end: w.end, value: w[key]! }))
    .sort((a, b) => a.start - b.start);
}

export function windowExtremes(windows: VocalWindow[]) {
  if (windows.length < 2) return null;
  return {
    low: windows.reduce((a, b) => (b.value < a.value ? b : a)),
    high: windows.reduce((a, b) => (b.value > a.value ? b : a)),
    count: windows.length,
  };
}

export function paceRange(metrics: Acoustics | null, duration: number) {
  const extremes = windowExtremes(paceWindows(metrics, duration));
  return extremes
    ? `${Math.round(extremes.low.value)}–${Math.round(extremes.high.value)} WPM`
    : "Unavailable";
}
