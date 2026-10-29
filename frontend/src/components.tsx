import {
  AlertCircle,
  ArrowRight,
  LoaderCircle,
  LockKeyhole,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Point } from "./types";

export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={18} />
      <div>{message}</div>
      {retry && (
        <button className="text-button" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}
export function Loading({
  label = "Opening your workspace…",
}: {
  label?: string;
}) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={21} />
      {label}
    </div>
  );
}
export function Empty({
  icon,
  title,
  children,
}: {
  icon?: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function PrivateNote() {
  return (
    <span className="private-note">
      <LockKeyhole size={13} /> Audio saved on your connected computer
    </span>
  );
}
export function NextButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button className="button primary" onClick={onClick} disabled={disabled}>
      {children}
      <ArrowRight size={17} />
    </button>
  );
}
export function MiniChart({
  points,
  label,
  unit,
  duration,
}: {
  points?: Point[];
  label: string;
  unit: string;
  duration: number;
}) {
  const valid = points?.filter((p) => p.value != null) ?? [];
  if (!valid.length)
    return (
      <div className="chart-empty">
        {label}: unavailable for this recording.
      </div>
    );
  const min = Math.min(...valid.map((p) => p.value!));
  const max = Math.max(...valid.map((p) => p.value!));
  const y = (value: number) => 75 - ((value - min) / (max - min || 1)) * 58;
  let path = "";
  let gap = true;
  for (const p of points!) {
    if (p.value == null) {
      gap = true;
      continue;
    }
    path += `${gap ? "M" : "L"}${((p.time / Math.max(duration, 1)) * 490 + 5).toFixed(1)},${y(p.value).toFixed(1)} `;
    gap = false;
  }
  return (
    <figure className="chart">
      <figcaption>
        <span>{label}</span>
        <span>
          {Math.round(min)}–{Math.round(max)} {unit}
        </span>
      </figcaption>
      <svg
        viewBox="0 0 500 90"
        role="img"
        aria-label={`${label}: ${Math.round(min)} to ${Math.round(max)} ${unit} over ${Math.round(duration)} seconds`}
      >
        <path className="chart-grid" d="M0 20H500M0 48H500M0 76H500" />
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="chart-axis">
        <span>0:00</span>
        <span>
          {Math.floor(duration / 60)}:
          {String(Math.floor(duration % 60)).padStart(2, "0")}
        </span>
      </div>
    </figure>
  );
}
