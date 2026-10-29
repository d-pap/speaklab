import { useRef, useState } from "react";
import { ArrowRight, Play } from "lucide-react";
import { timeLabel } from "./api";
import { MiniChart } from "./components";
import { acousticWindows, paceWindows, windowExtremes } from "./vocalMetrics";
import type { VocalWindow } from "./vocalMetrics";
import type { Attempt } from "./types";

const foundations = [
  "Rate",
  "Volume",
  "Pitch & melody",
  "Pauses",
  "Tonality",
] as const;
type Foundation = (typeof foundations)[number];

export function VocalVariation({
  attempt,
  style,
}: {
  attempt: Attempt;
  style: string;
}) {
  const [foundation, setFoundation] = useState<Foundation>("Rate");
  const [playError, setPlayError] = useState("");
  const [audioReady, setAudioReady] = useState(false);
  const player = useRef<HTMLAudioElement>(null);
  const m = attempt.acoustics;
  const duration = attempt.duration;
  const rate = windowExtremes(paceWindows(m, duration));
  const volumeWindows = acousticWindows(m, duration, "loudness_range_db");
  const pitchWindows = acousticWindows(m, duration, "pitch_range_semitones");
  const volume = windowExtremes(volumeWindows);
  const pitch = windowExtremes(pitchWindows);
  const pauses = (m?.pauses ?? [])
    .filter(
      (p) =>
        Number.isFinite(p.start) &&
        Number.isFinite(p.duration) &&
        p.start >= 0 &&
        p.duration > 0 &&
        p.start < duration,
    )
    .sort((a, b) => a.start - b.start);
  const pauseSeconds = pauses.reduce(
    (sum, p) => sum + Math.min(p.duration, duration - p.start),
    0,
  );
  const shortest = pauses.reduce<(typeof pauses)[number] | null>(
    (a, p) => (!a || p.duration < a.duration ? p : a),
    null,
  );
  const longest = pauses.reduce<(typeof pauses)[number] | null>(
    (a, p) => (!a || p.duration > a.duration ? p : a),
    null,
  );
  async function listen(time: number) {
    if (!player.current) return;
    setPlayError("");
    player.current.currentTime = Math.max(0, time - 0.3);
    try {
      await player.current.play();
    } catch {
      setPlayError("Press play to listen from the selected timestamp.");
    }
  }
  function passage(
    window: VocalWindow,
    label: string,
    unit: string,
    digits = 0,
  ) {
    return (
      <button
        className="variation-passage"
        disabled={!audioReady}
        onClick={() => void listen(window.start)}
      >
        <Play size={14} />
        <span>
          {label}
          <small>
            {timeLabel(window.start)}–{timeLabel(window.end)}
          </small>
        </span>
        <strong>
          {window.value.toFixed(digits)} {unit}
        </strong>
      </button>
    );
  }
  function rangeChart(windows: VocalWindow[], label: string, unit: string) {
    return (
      <MiniChart
        points={windows.map((w) => ({
          time: (w.start + w.end) / 2,
          value: w.value,
        }))}
        label={label}
        unit={unit}
        duration={duration}
      />
    );
  }
  return (
    <section
      className="variation-review"
      aria-label={`Vocal variation for attempt ${attempt.number}`}
    >
      <div className="variation-heading">
        <h3>Vocal variation</h3>
        <span>Listen for purposeful contrast</span>
      </div>
      <p className="small muted">
        Your intended style: {style.toLowerCase()}. These measurements locate
        changes; they do not grade how engaging you sound.
      </p>
      <div
        className="foundation-switch"
        role="group"
        aria-label="Choose a vocal foundation"
      >
        {foundations.map((name) => (
          <button
            key={name}
            aria-pressed={foundation === name}
            onClick={() => setFoundation(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="variation-content" aria-live="polite">
        {foundation === "Rate" && (
          <>
            <h4>Pace across your explanation</h4>
            {rate ? (
              <>
                <p className="variation-reading">
                  <strong>
                    {Math.round(rate.low.value)}–{Math.round(rate.high.value)}
                  </strong>
                  <span>
                    estimated WPM across {rate.count} full 30-second windows
                  </span>
                </p>
                <MiniChart
                  points={paceWindows(m, duration).map((w) => ({
                    time: (w.start + w.end) / 2,
                    value: w.value,
                  }))}
                  label="Estimated pace over time"
                  unit="WPM"
                  duration={duration}
                />
                {rate.high.value === rate.low.value ? (
                  <p className="small muted">
                    The rounded window estimates are equal. This cannot rule out
                    changes within sentences.
                  </p>
                ) : (
                  <div className="variation-passages">
                    {passage(rate.low, "Slowest window", "WPM")}
                    {passage(rate.high, "Fastest window", "WPM")}
                  </div>
                )}
              </>
            ) : (
              <p className="variation-unavailable">
                Pace variation needs timestamped transcription covering at least
                two full 30-second windows. A manually edited transcript has no
                aligned pace estimates.
              </p>
            )}
            <p className="variation-practice">
              <strong>Try this</strong> Slow down for one important explanation,
              then return to your natural pace. Listen to whether that contrast
              clarifies the point.
            </p>
            <p className="small muted">
              WPM includes pauses. Words are distributed across transcription
              segments, so these are coarse estimates, not word-level speed or
              proof of emphasis. Short trailing windows are excluded.
            </p>
          </>
        )}
        {foundation === "Volume" && (
          <>
            <h4>Contrast in recorded volume</h4>
            {volume ? (
              <>
                <p className="variation-reading">
                  <strong>
                    {volume.low.value.toFixed(1)}–{volume.high.value.toFixed(1)}{" "}
                    dB
                  </strong>
                  <span>
                    within-window loudness spread across {volume.count} usable
                    15-second windows
                  </span>
                </p>
                {rangeChart(
                  volumeWindows,
                  "Local loudness variation over time",
                  "dB spread",
                )}
                <div className="variation-passages">
                  {passage(volume.low, "Least varied window", "dB", 1)}
                  {volume.high.start !== volume.low.start &&
                    passage(volume.high, "Most varied window", "dB", 1)}
                </div>
              </>
            ) : (
              <p className="variation-unavailable">
                Local volume comparison needs at least two full 15-second
                windows with enough active audio. Whole-recording levels may
                still be available below.
              </p>
            )}
            <p className="variation-practice">
              <strong>Try this</strong> Say one key phrase a little more firmly,
              then soften the supporting detail. Compare the meaning rather than
              trying to maximize the range.
            </p>
            <details>
              <summary>Recorded level and measurement limits</summary>
              <MiniChart
                points={m?.loudness_track}
                label="Recorded level over time"
                unit="dBFS"
                duration={duration}
              />
              <p className="small muted">
                Spread is the difference between the 10th and 90th percentile
                active-audio levels within each window. Least varied does not
                mean quietest. These are relative recording levels; microphone
                movement, input gain and automatic processing can create or
                conceal changes.
              </p>
            </details>
          </>
        )}
        {foundation === "Pitch & melody" && (
          <>
            <h4>Changes in pitch and melody</h4>
            {pitch ? (
              <>
                <p className="variation-reading">
                  <strong>
                    {pitch.low.value.toFixed(1)}–{pitch.high.value.toFixed(1)}{" "}
                    st
                  </strong>
                  <span>
                    within-window pitch spread across {pitch.count} usable
                    15-second windows
                  </span>
                </p>
                {rangeChart(
                  pitchWindows,
                  "Local pitch variation over time",
                  "semitones",
                )}
                <div className="variation-passages">
                  {passage(pitch.low, "Narrowest pitch spread", "st", 1)}
                  {pitch.high.start !== pitch.low.start &&
                    passage(pitch.high, "Widest pitch spread", "st", 1)}
                </div>
              </>
            ) : (
              <p className="variation-unavailable">
                Local pitch comparison needs at least two full 15-second windows
                with enough tracked voiced audio. Missing pitch estimates are
                not evidence of a monotone voice.
              </p>
            )}
            <p className="variation-practice">
              <strong>Try this</strong> Say the same sentence twice, emphasizing
              a different word each time. Listen to how the meaning changes; a
              larger pitch spread is not automatically better.
            </p>
            <details>
              <summary>Pitch contour and measurement limits</summary>
              <MiniChart
                points={m?.pitch_track}
                label="Estimated pitch contour"
                unit="Hz"
                duration={duration}
              />
              <p className="small muted">
                Semitones describe relative pitch distance. Each spread uses the
                10th and 90th percentiles of tracked voiced pitch. Tracking can
                miss soft, creaky, very low or high passages, or jump an octave.
                A narrow spread alone cannot establish monotone delivery.
              </p>
            </details>
          </>
        )}
        {foundation === "Pauses" && (
          <>
            <h4>Space between ideas</h4>
            {m?.pause_count == null ? (
              <p className="variation-unavailable">
                Pause analysis is unavailable for this recording.
              </p>
            ) : (
              <>
                <p className="variation-reading">
                  <strong>{pauses.length} internal pauses</strong>
                  <span>
                    {pauseSeconds.toFixed(1)} seconds total
                    {duration > 0
                      ? ` · ${Math.round((pauseSeconds / duration) * 100)}% of the recording`
                      : ""}
                  </span>
                </p>
                {shortest && longest ? (
                  <>
                    <p className="small muted">
                      Detected durations range from{" "}
                      {shortest.duration.toFixed(1)} to{" "}
                      {longest.duration.toFixed(1)} seconds.
                    </p>
                    <div
                      className="pause-strip"
                      role="img"
                      aria-label={`${pauses.length} internal pauses across ${Math.round(duration)} seconds`}
                    >
                      {pauses.map((p, i) => (
                        <span
                          key={i}
                          style={{
                            left: `${(p.start / duration) * 100}%`,
                            width: `${(Math.min(p.duration, duration - p.start) / duration) * 100}%`,
                          }}
                        />
                      ))}
                    </div>
                    <div className="chart-axis">
                      <span>0:00</span>
                      <span>{timeLabel(duration)}</span>
                    </div>
                    <div className="variation-passages">
                      <button
                        className="variation-passage"
                        disabled={!audioReady}
                        onClick={() => void listen(longest.start)}
                      >
                        <Play size={14} />
                        <span>
                          Longest internal pause
                          <small>{timeLabel(longest.start)}</small>
                        </span>
                        <strong>{longest.duration.toFixed(1)} s</strong>
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="small muted">
                    No internal energy gaps of at least 0.3 seconds were
                    detected. That does not establish uninterrupted speech.
                  </p>
                )}
              </>
            )}
            <p className="variation-practice">
              <strong>Try this</strong> Leave a short pause after a complex
              idea, then listen to whether it gives the explanation room to
              land. A longer or more frequent pause is not inherently better.
            </p>
            <p className="small muted">
              Energy-based gaps may miss soft speech or count background noise
              as speech. Leading and trailing silence are excluded here. Pause
              locations are not aligned to exact words.
            </p>
          </>
        )}
        {foundation === "Tonality" && (
          <>
            <h4>Match your delivery to your intention</h4>
            <p>
              Listen for whether your {style.toLowerCase()} delivery conveys
              what you intended. Acoustic variation cannot reliably establish an
              emotion, confidence, charisma or an audience’s reaction.
            </p>
            <p className="variation-practice">
              <strong>Try this</strong> Choose a sentence and say it with two
              intentions—for example, curious and reassuring. You can experiment
              with facial expression. Listen back and decide which delivery fits
              your message.
            </p>
            <button
              className="text-button"
              disabled={!audioReady}
              onClick={() => void listen(0)}
            >
              Listen from the start <ArrowRight size={14} />
            </button>
            <p className="small muted">
              Listening exercise · no emotion or tonality score is inferred from
              the recording.
            </p>
          </>
        )}
      </div>
      <audio
        ref={player}
        controls
        preload="metadata"
        src={attempt.audio_url}
        onLoadedMetadata={() => setAudioReady(true)}
        onError={() => {
          setAudioReady(false);
          setPlayError(
            "Audio playback is unavailable. Reload the page to retry loading the saved recording.",
          );
        }}
        aria-label={`Listen to vocal variation in attempt ${attempt.number}`}
      />
      {playError && (
        <p className="small muted" role="status">
          {playError}
        </p>
      )}
    </section>
  );
}
