import { useMemo, useState } from "react";
import { MetricCard } from "./MetricCard";
import { FileStatusPill, RiskPill, StatusPill } from "./StatusPill";
import type {
  ContextOSDesktopData,
  FileRecord,
  NavigationSection,
} from "../types/contextos";

function PanelHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="panel-header">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}

function OverviewPanel({ data }: { data: ContextOSDesktopData }) {
  const metrics = data.overview;

  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Overview Dashboard"
        title="AI development observability"
        description="An operating view across task intent, tokens, files, scope drift, and trust."
      />
      <div className="metric-grid">
        <MetricCard label="Current Task" value={metrics.currentTask} />
        <MetricCard label="Tokens Used" value={metrics.tokensUsed.toLocaleString()} />
        <MetricCard label="Estimated Cost" value={metrics.estimatedCost} />
        <MetricCard label="Files Read" value={String(metrics.filesRead)} />
        <MetricCard label="Files Modified" value={String(metrics.filesModified)} />
        <MetricCard
          label="Scope Drift"
          value={metrics.scopeDrift}
          helper="policy fallback observed"
          tone="warning"
        />
        <MetricCard
          label="Trust Score"
          value={`${metrics.trustScore}/100`}
          helper="reduced by governance review"
          tone="success"
        />
      </div>
    </section>
  );
}

function CurrentTaskPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Current Task"
        title="Intent and agent activity"
        description="The active user intent and a chronological view of agent behavior."
      />
      <div className="stack">
        <article className="content-card">
          <h2>User Intent</h2>
          <p>{data.currentTask.userIntent}</p>
        </article>
        <article className="content-card">
          <h2>Current Status</h2>
          <p>{data.currentTask.currentStatus}</p>
        </article>
        <article className="content-card">
          <h2>Agent Activity Timeline</h2>
          <div className="timeline">
            {data.currentTask.timeline.map((event) => (
              <div className="timeline-event" key={`${event.time}-${event.title}`}>
                <span>{event.time}</span>
                <div>
                  <StatusPill label={event.type} tone="info" />
                  <strong>{event.title}</strong>
                  <p>{event.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function fileMatchesSearch(file: FileRecord, searchTerm: string): boolean {
  const normalizedSearch = searchTerm.trim().toLowerCase();
  if (!normalizedSearch) {
    return true;
  }

  return [file.path, file.status, file.risk, file.lastModified].some((value) =>
    value.toLowerCase().includes(normalizedSearch),
  );
}

function FilesPanel({ data }: { data: ContextOSDesktopData }) {
  const [searchTerm, setSearchTerm] = useState("");
  const filteredFiles = useMemo(
    () => data.files.filter((file) => fileMatchesSearch(file, searchTerm)),
    [data.files, searchTerm],
  );

  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Files"
        title="Searchable file risk table"
        description="File observations across allowed, review-required, protected, and blocked statuses."
      />
      <label className="search-box">
        <span>Search files</span>
        <input
          onChange={(event) => setSearchTerm(event.target.value)}
          placeholder="Filter by path, status, risk..."
          type="search"
          value={searchTerm}
        />
      </label>
      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>File Path</th>
              <th>Status</th>
              <th>Risk</th>
              <th>Last Modified</th>
            </tr>
          </thead>
          <tbody>
            {filteredFiles.map((file) => (
              <tr key={file.path}>
                <td>
                  <code>{file.path}</code>
                </td>
                <td>
                  <FileStatusPill status={file.status} />
                </td>
                <td>
                  <RiskPill risk={file.risk} />
                </td>
                <td>{file.lastModified}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ScopeAnalysisPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Scope Analysis"
        title="Expected vs observed scope"
        description="A drift score showing whether observed work stayed inside the intended boundary."
      />
      <div className="scope-layout">
        <article className="content-card">
          <h2>Expected Scope</h2>
          <ul className="path-list">
            {data.scopeAnalysis.expectedScope.map((path) => (
              <li key={path}>
                <code>{path}</code>
              </li>
            ))}
          </ul>
        </article>
        <article className="content-card">
          <h2>Observed Scope</h2>
          <ul className="path-list">
            {data.scopeAnalysis.observedScope.map((path) => (
              <li key={path}>
                <code>{path}</code>
              </li>
            ))}
          </ul>
        </article>
      </div>
      <article className="content-card drift-card">
        <div>
          <span>Scope Drift Score</span>
          <strong>{data.scopeAnalysis.scopeDriftScore}%</strong>
        </div>
        <p>{data.scopeAnalysis.explanation}</p>
      </article>
    </section>
  );
}

function TokenUsagePanel({ data }: { data: ContextOSDesktopData }) {
  const usage = data.tokenUsage;
  const percentage = Math.round((usage.currentUsage / usage.tokenBudget) * 100);
  const maxTokens = Math.max(...usage.usageTrend.map((point) => point.tokens));

  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Token Usage"
        title="Budget, trend, and savings"
        description="Mock observability for token budget pressure and optimization opportunities."
      />
      <div className="metric-grid metric-grid--compact">
        <MetricCard label="Token Budget" value={usage.tokenBudget.toLocaleString()} />
        <MetricCard label="Current Usage" value={usage.currentUsage.toLocaleString()} />
        <MetricCard label="Budget Used" value={`${percentage}%`} tone="warning" />
      </div>
      <article className="content-card">
        <h2>Usage Trend Chart</h2>
        <div className="trend-chart">
          {usage.usageTrend.map((point) => (
            <div className="trend-bar" key={point.label}>
              <div
                className="trend-bar__fill"
                style={{ height: `${Math.max((point.tokens / maxTokens) * 100, 8)}%` }}
              />
              <span>{point.label}</span>
            </div>
          ))}
        </div>
      </article>
      <article className="content-card">
        <h2>Estimated Savings Opportunities</h2>
        <ul className="insight-list">
          {usage.estimatedSavingsOpportunities.map((opportunity) => (
            <li key={opportunity}>{opportunity}</li>
          ))}
        </ul>
      </article>
    </section>
  );
}

function ConstitutionPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Constitution"
        title="Active rules and recommendations"
        description="Mock governance rules with suggested improvements for safer agent behavior."
      />
      <div className="stack">
        <article className="content-card">
          <h2>Active Rules</h2>
          <div className="rule-grid">
            {data.constitution.activeRules.map((rule) => (
              <div className="rule-card" key={rule.id}>
                <div>
                  <code>{rule.id}</code>
                  <RiskPill risk={rule.severity} />
                </div>
                <strong>{rule.title}</strong>
                <p>{rule.description}</p>
              </div>
            ))}
          </div>
        </article>
        <article className="content-card">
          <h2>Suggested Improvements</h2>
          <div className="recommendation-list">
            {data.constitution.suggestedImprovements.map((recommendation) => (
              <div className="recommendation" key={recommendation.id}>
                <div>
                  <strong>{recommendation.title}</strong>
                  <p>{recommendation.description}</p>
                  <small>{recommendation.impact}</small>
                </div>
                <button type="button">Apply Recommendation</button>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function AuditLogPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Audit Log"
        title="Chronological development events"
        description="Mock local observability stream for reads, writes, searches, constitution changes, and approvals."
      />
      <div className="audit-list">
        {data.auditLog.map((event) => (
          <article className="audit-event" key={`${event.time}-${event.target}`}>
            <span>{event.time}</span>
            <div>
              <StatusPill label={event.type} tone="neutral" />
              <strong>{event.target}</strong>
              <p>{event.detail}</p>
              <small>{event.actor}</small>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function SettingsPanel({ data }: { data: ContextOSDesktopData }) {
  return (
    <section className="workspace-panel">
      <PanelHeader
        eyebrow="Settings"
        title="Desktop mock controls"
        description="Static settings that describe the current mock-first GUI behavior."
      />
      <div className="settings-list">
        {data.settings.map((setting) => (
          <article className="setting-card" key={setting.title}>
            <div>
              <h2>{setting.title}</h2>
              <p>{setting.description}</p>
            </div>
            <StatusPill
              label={setting.enabled ? "Enabled" : "Disabled"}
              tone={setting.enabled ? "success" : "neutral"}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

export function WorkspacePanel({
  activeSection,
  data,
}: {
  activeSection: NavigationSection;
  data: ContextOSDesktopData;
}) {
  switch (activeSection) {
    case "current-task":
      return <CurrentTaskPanel data={data} />;
    case "files":
      return <FilesPanel data={data} />;
    case "scope-analysis":
      return <ScopeAnalysisPanel data={data} />;
    case "token-usage":
      return <TokenUsagePanel data={data} />;
    case "constitution":
      return <ConstitutionPanel data={data} />;
    case "audit-log":
      return <AuditLogPanel data={data} />;
    case "settings":
      return <SettingsPanel data={data} />;
    case "overview":
    default:
      return <OverviewPanel data={data} />;
  }
}
