import type { FileStatus, RiskLevel } from "../types/contextos";

export type PillTone = "success" | "warning" | "danger" | "neutral" | "info";

const statusTone: Record<FileStatus, PillTone> = {
  Allowed: "success",
  "Review Required": "warning",
  Protected: "info",
  Blocked: "danger",
};

const riskTone: Record<RiskLevel, PillTone> = {
  Low: "success",
  Medium: "warning",
  High: "info",
  Critical: "danger",
};

export function StatusPill({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: PillTone;
}) {
  return <span className={`status-pill status-pill--${tone}`}>{label}</span>;
}

export function FileStatusPill({ status }: { status: FileStatus }) {
  return <StatusPill label={status} tone={statusTone[status]} />;
}

export function RiskPill({ risk }: { risk: RiskLevel }) {
  return <StatusPill label={risk} tone={riskTone[risk]} />;
}
