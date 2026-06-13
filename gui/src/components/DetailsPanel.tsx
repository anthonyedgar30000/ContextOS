import { StatusPill } from "./StatusPill";
import type { ContextOSDesktopData } from "../types/contextos";

const signalTone = {
  neutral: "neutral",
  success: "success",
  warning: "warning",
  danger: "danger",
} as const;

export function DetailsPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <aside className="details-panel" aria-label="Assurance details">
      <section className="details-card decision-summary">
        <p className="eyebrow">Assurance Decision</p>
        <strong>{data.details.finalDecision}</strong>
        <StatusPill label={`Confidence: ${data.details.confidence}`} tone="warning" />
        <p>{data.details.trustSummary}</p>
      </section>

      <section className="details-card">
        <h2>Signal Stack</h2>
        <div className="signal-list">
          {data.details.signals.map((signal) => (
            <div className="signal-row" key={signal.label}>
              <span>{signal.label}</span>
              <StatusPill label={signal.value} tone={signalTone[signal.tone]} />
            </div>
          ))}
        </div>
      </section>

      <section className="details-card">
        <h2>Task Boundary</h2>
        <dl className="meta-list">
          <div>
            <dt>Repository</dt>
            <dd>{data.repository}</dd>
          </div>
          <div>
            <dt>Branch</dt>
            <dd>{data.branch}</dd>
          </div>
          <div>
            <dt>Project</dt>
            <dd>{data.project}</dd>
          </div>
        </dl>
      </section>
    </aside>
  );
}
