import { assuranceSummary, type ChangeFinding } from "./mockData";

const classificationLabels: Record<ChangeFinding["classification"], string> = {
  intent_allowed: "Intent allowed",
  policy_allowed: "Policy allowed",
  review_required: "Review required",
  blocked: "Blocked",
  default_review_required: "Default review",
};

function StatCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warning" | "success";
}) {
  return (
    <section className={`stat-card stat-card--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </section>
  );
}

function PathList({ title, paths }: { title: string; paths: string[] }) {
  return (
    <section className="panel">
      <div className="panel__header">
        <h2>{title}</h2>
      </div>
      <ul className="path-list">
        {paths.map((path) => (
          <li key={path}>
            <code>{path}</code>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FindingRow({ finding }: { finding: ChangeFinding }) {
  return (
    <tr>
      <td>
        <code>{finding.path}</code>
      </td>
      <td>
        <span className={`pill pill--${finding.classification}`}>
          {classificationLabels[finding.classification]}
        </span>
      </td>
      <td className={`confidence confidence--${finding.confidence}`}>
        {finding.confidence}
      </td>
      <td>{finding.reason}</td>
    </tr>
  );
}

function App() {
  const reviewCount = assuranceSummary.findings.filter(
    (finding) => finding.classification === "review_required",
  ).length;
  const intentAllowedCount = assuranceSummary.findings.filter(
    (finding) => finding.classification === "intent_allowed",
  ).length;

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">ContextOS Desktop</p>
          <h1>Local assurance cockpit</h1>
          <p className="hero__copy">
            A mock-first desktop view for Intent Contracts, repository policy,
            observed Git state, and the resulting assurance decision.
          </p>
        </div>
        <div className="decision-card">
          <span>Final decision</span>
          <strong>{assuranceSummary.finalDecision}</strong>
          <small>Confidence: {assuranceSummary.confidence}</small>
        </div>
      </header>

      <section className="stats-grid" aria-label="Repository state summary">
        <StatCard label="Repository" value={assuranceSummary.repository} />
        <StatCard label="Branch" value={assuranceSummary.branch} />
        <StatCard label="Base" value={assuranceSummary.base} />
        <StatCard
          label="Intent matches"
          value={String(intentAllowedCount)}
          tone="success"
        />
        <StatCard
          label="Human reviews"
          value={String(reviewCount)}
          tone="warning"
        />
      </section>

      <section className="panel decision-panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Assurance decision flow</p>
            <h2>Intent Contract + Policy + Observed Git State</h2>
          </div>
        </div>
        <div className="flow">
          <span>Intent Contract</span>
          <span>Repository Policy</span>
          <span>Observed Git State</span>
          <strong>Assurance Decision</strong>
        </div>
        <p>{assuranceSummary.reason}</p>
      </section>

      <section className="two-column">
        <PathList
          title="Intent Contract allowed paths"
          paths={assuranceSummary.intentAllowedPaths}
        />
        <PathList
          title="Policy fallback governance paths"
          paths={assuranceSummary.policyFallbackPaths}
        />
      </section>

      <section className="panel">
        <div className="panel__header">
          <div>
            <p className="eyebrow">Changed files</p>
            <h2>Classification findings</h2>
          </div>
          <div className="source-paths">
            <span>Contract: {assuranceSummary.contractPath}</span>
            <span>Policy: {assuranceSummary.policyPath}</span>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Classification</th>
                <th>Confidence</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {assuranceSummary.findings.map((finding) => (
                <FindingRow key={finding.path} finding={finding} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

export default App;
