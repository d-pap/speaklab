import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  CircleStop,
  Mic,
  Pause,
  Play,
  RotateCcw,
  Upload,
  Download,
  AudioLines,
} from "lucide-react";
import { api, errorText, timeLabel } from "./api";
import { ErrorNotice, PrivateNote } from "./components";
import type { Session } from "./types";

export function Recorder({
  session,
  number,
  onSaved,
  onDirty,
}: {
  session: Session;
  number: number;
  onSaved: () => Promise<void>;
  onDirty: (value: boolean) => void;
}) {
  const [state, setState] = useState<
    "idle" | "requesting" | "recording" | "paused" | "stopped"
  >("idle");
  const [elapsed, setElapsed] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const context = useRef<AudioContext | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const frame = useRef(0);
  const accumulated = useRef(0);
  const started = useRef(0);
  const mounted = useRef(true);
  const chunks = useRef<Blob[]>([]);

  function release() {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (context.current && context.current.state !== "closed")
      void context.current.close();
    context.current = null;
    cancelAnimationFrame(frame.current);
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (recorder.current && recorder.current.state !== "inactive")
        recorder.current.stop();
      release();
      onDirty(false);
    };
  }, [onDirty]);
  useEffect(() => {
    if (!blob) {
      setUrl("");
      return;
    }
    const value = URL.createObjectURL(blob);
    setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [blob]);
  useEffect(() => {
    if (state !== "recording") return;
    const id = window.setInterval(() => {
      const value =
        accumulated.current + (performance.now() - started.current) / 1000;
      setElapsed(Math.min(value, session.duration));
      if (value >= session.duration) stop();
    }, 100);
    return () => clearInterval(id);
  }, [state, session.duration]);
  useEffect(() => {
    if (state === "idle") return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [state]);

  async function start() {
    if (
      blob &&
      !window.confirm("Replace this unsaved recording with a new attempt?")
    )
      return;
    setError("");
    setState("requesting");
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error(
          "This browser cannot record here. Use a recent browser on localhost, or import an audio file below.",
        );
      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      if (!mounted.current) {
        media.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = media;
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find(
        (m) => MediaRecorder.isTypeSupported(m),
      );
      const rec = new MediaRecorder(
        media,
        mime ? { mimeType: mime } : undefined,
      );
      recorder.current = rec;
      chunks.current = [];
      rec.ondataavailable = (event) => {
        if (event.data.size) chunks.current.push(event.data);
      };
      rec.onstop = () => {
        if (mounted.current) {
          setBlob(new Blob(chunks.current, { type: rec.mimeType }));
          setState("stopped");
        }
        release();
      };
      rec.onerror = () => {
        setError(
          "Recording was interrupted. Play back the captured audio before saving it.",
        );
        if (rec.state !== "inactive") rec.stop();
        release();
      };
      const ctx = new AudioContext();
      context.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      ctx.createMediaStreamSource(media).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      function draw() {
        if (!canvas.current || !mounted.current) return;
        const c = canvas.current.getContext("2d");
        if (!c) return;
        const w = canvas.current.width;
        const h = canvas.current.height;
        analyser.getByteTimeDomainData(data);
        c.clearRect(0, 0, w, h);
        const color = getComputedStyle(document.documentElement)
          .getPropertyValue("--accent")
          .trim();
        c.fillStyle = color;
        for (let i = 0; i < 64; i++) {
          let sum = 0;
          for (let j = 0; j < 32; j++)
            sum += Math.abs(data[i * 32 + j] - 128) / 128;
          const height =
            rec.state === "paused"
              ? 3
              : Math.max(3, Math.min(h - 8, (sum / 32) * h * 3));
          c.beginPath();
          c.roundRect(
            (i * w) / 64 + 2,
            (h - height) / 2,
            w / 64 - 4,
            height,
            3,
          );
          c.fill();
        }
        frame.current = requestAnimationFrame(draw);
      }
      accumulated.current = 0;
      started.current = performance.now();
      setElapsed(0);
      setBlob(null);
      rec.start(250);
      setState("recording");
      onDirty(true);
      frame.current = requestAnimationFrame(draw);
    } catch (e) {
      release();
      setState(blob ? "stopped" : "idle");
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone access was denied. Allow microphone access in your browser’s site settings, then try again. You can also import a recording."
          : errorText(e),
      );
    }
  }
  function pause() {
    if (recorder.current?.state === "recording") {
      accumulated.current += (performance.now() - started.current) / 1000;
      recorder.current.pause();
      setState("paused");
    } else if (recorder.current?.state === "paused") {
      started.current = performance.now();
      recorder.current.resume();
      setState("recording");
    }
  }
  function stop() {
    if (recorder.current && recorder.current.state !== "inactive")
      recorder.current.stop();
  }
  async function save() {
    if (!blob || saving) return;
    setSaving(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", blob, "recording");
      await api(`/sessions/${session.id}/attempts/${number}`, {
        method: "POST",
        body: form,
      });
      onDirty(false);
      await onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }
  const active = state === "recording" || state === "paused";
  return (
    <div className="record-page">
      <div className="record-heading">
        <span className="eyebrow">
          ATTEMPT {number} · {number === 1 ? "FROM MEMORY" : "MAKE IT YOUR OWN"}
        </span>
        <h1>{session.topic.title}</h1>
        <p>{session.prompt}</p>
      </div>
      <section
        className={`record-card ${state === "recording" ? "is-recording" : ""}`}
      >
        <div className="record-status" role="status">
          <span
            className={`status-dot ${state === "recording" ? "live" : ""}`}
          />
          {
            {
              idle: "A moment to find your voice",
              requesting: "Waiting for microphone access…",
              recording: "Recording your explanation",
              paused: "Paused · take a breath",
              stopped: "Your explanation, captured",
            }[state]
          }
        </div>
        <div
          className="timer"
          aria-label={`${timeLabel(Math.max(0, session.duration - elapsed))} remaining`}
        >
          {timeLabel(Math.max(0, session.duration - elapsed))}
        </div>
        <p className="timer-caption">
          {state === "stopped"
            ? "Ready when you are"
            : `${session.duration / 60} minute practice · ${session.style.toLowerCase()}`}
        </p>
        <div className="waveform">
          <canvas
            ref={canvas}
            width="768"
            height="120"
            aria-label="Live microphone activity"
          />
          {!active && state !== "stopped" && (
            <div className="wave-idle" aria-hidden="true">
              {Array.from({ length: 56 }, (_, i) => (
                <span
                  key={i}
                  style={{ height: `${4 + Math.sin(i * 0.55) ** 2 * 18}px` }}
                />
              ))}
            </div>
          )}
        </div>
        <div className="record-controls">
          {active ? (
            <>
              <button className="button secondary" onClick={pause}>
                {state === "paused" ? <Play size={17} /> : <Pause size={17} />}{" "}
                {state === "paused" ? "Resume" : "Pause"}
              </button>
              <button className="button primary" onClick={stop}>
                <CircleStop size={18} /> Finish recording
              </button>
            </>
          ) : (
            <button
              className="button primary record-start"
              onClick={() => void start()}
              disabled={state === "requesting" || saving}
            >
              {state === "stopped" ? (
                <RotateCcw size={18} />
              ) : (
                <Mic size={18} />
              )}{" "}
              {state === "stopped"
                ? "Record again"
                : state === "requesting"
                  ? "Connecting microphone…"
                  : "Start recording"}
            </button>
          )}
        </div>
        <div className="record-tip">
          {number === 1
            ? "Start with what you know. The gaps are where learning begins."
            : "Explain the idea in your own words. You don’t need a perfect script."}
        </div>
        {blob && (
          <div className="playback-draft">
            <audio
              controls
              src={url}
              aria-label="Play your unsaved recording"
            />
            <a
              className="text-button"
              href={url}
              download={`speaklab-attempt-${number}.${blob.type.includes("mp4") ? "mp4" : blob.type.includes("wav") ? "wav" : "webm"}`}
            >
              <Download size={15} /> Keep a copy
            </a>
          </div>
        )}
      </section>
      {error && <ErrorNotice message={error} />}
      <div className="record-footer">
        <PrivateNote />
        {blob ? (
          <button
            className="button primary"
            disabled={saving}
            onClick={() => void save()}
          >
            {saving
              ? "Saving your audio…"
              : number === 1
                ? "Save & explore feedback"
                : "Save & compare attempts"}
            <ArrowRight size={17} />
          </button>
        ) : (
          <label className={`text-button import ${active ? "disabled" : ""}`}>
            <Upload size={15} /> Import audio
            <input
              type="file"
              accept="audio/*,.webm,.mp4"
              disabled={active || state === "requesting"}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  if (file.size > 30 * 1024 * 1024) {
                    setError("Choose an audio file under 30 MB.");
                    return;
                  }
                  setBlob(file);
                  setState("stopped");
                  setError("");
                  onDirty(true);
                }
                e.target.value = "";
              }}
            />
          </label>
        )}
      </div>
      <div className="gentle-note">
        <AudioLines size={18} />
        <span>
          Listen for one clear idea, one concrete example, and a natural place
          to pause.
        </span>
      </div>
    </div>
  );
}
