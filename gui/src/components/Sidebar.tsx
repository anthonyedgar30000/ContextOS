import type { NavigationSection } from "../types/contextos";

export interface NavItem {
  id: NavigationSection;
  label: string;
  description: string;
}

export const navItems: NavItem[] = [
  { id: "overview", label: "Overview", description: "Assurance summary" },
  { id: "current-task", label: "Current Task", description: "Intent and activity" },
  { id: "files", label: "Files", description: "Risk by path" },
  { id: "scope-analysis", label: "Scope Analysis", description: "Drift detection" },
  { id: "token-usage", label: "Token Usage", description: "Budget and savings" },
  { id: "constitution", label: "Constitution", description: "Rules and advice" },
  { id: "audit-log", label: "Audit Log", description: "Chronological events" },
  { id: "settings", label: "Settings", description: "Desktop controls" },
];

export function Sidebar({
  activeSection,
  onSectionChange,
}: {
  activeSection: NavigationSection;
  onSectionChange: (section: NavigationSection) => void;
}) {
  return (
    <aside className="sidebar" aria-label="ContextOS navigation">
      <div className="brand">
        <div className="brand__mark">C</div>
        <div>
          <strong>ContextOS</strong>
          <span>Desktop Assurance</span>
        </div>
      </div>

      <nav className="nav-list">
        {navItems.map((item) => (
          <button
            className={`nav-item ${
              activeSection === item.id ? "nav-item--active" : ""
            }`}
            key={item.id}
            onClick={() => onSectionChange(item.id)}
            type="button"
          >
            <span>{item.label}</span>
            <small>{item.description}</small>
          </button>
        ))}
      </nav>
    </aside>
  );
}
