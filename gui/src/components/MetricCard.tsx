export function MetricCard({
  label,
  value,
  helper,
  tone = "neutral",
}: {
  label: string;
  value: string;
  helper?: string;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {helper ? <small>{helper}</small> : null}
    </article>
  );
}
