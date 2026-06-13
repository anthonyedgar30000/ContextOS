export type NavigationSection =
  | "overview"
  | "current-task"
  | "files"
  | "scope-analysis"
  | "token-usage"
  | "constitution"
  | "audit-log"
  | "settings";

export type FileStatus = "Allowed" | "Review Required" | "Protected" | "Blocked";

export type RiskLevel = "Low" | "Medium" | "High" | "Critical";

export type TimelineEventType =
  | "planning"
  | "read"
  | "search"
  | "write"
  | "verification";

export type AuditEventType =
  | "File Read"
  | "File Write"
  | "Search"
  | "Constitution Change"
  | "User Approval";

export interface OverviewMetrics {
  currentTask: string;
  tokensUsed: number;
  estimatedCost: string;
  filesRead: number;
  filesModified: number;
  scopeDrift: string;
  trustScore: number;
}

export interface TimelineEvent {
  time: string;
  type: TimelineEventType;
  title: string;
  detail: string;
}

export interface CurrentTask {
  userIntent: string;
  currentStatus: string;
  timeline: TimelineEvent[];
}

export interface FileRecord {
  path: string;
  status: FileStatus;
  risk: RiskLevel;
  lastModified: string;
}

export interface ScopeAnalysis {
  expectedScope: string[];
  observedScope: string[];
  scopeDriftScore: number;
  explanation: string;
}

export interface TokenTrendPoint {
  label: string;
  tokens: number;
}

export interface TokenUsage {
  tokenBudget: number;
  currentUsage: number;
  estimatedSavingsOpportunities: string[];
  usageTrend: TokenTrendPoint[];
}

export interface ConstitutionRule {
  id: string;
  title: string;
  description: string;
  severity: RiskLevel;
}

export interface ConstitutionRecommendation {
  id: string;
  title: string;
  description: string;
  impact: string;
}

export interface Constitution {
  activeRules: ConstitutionRule[];
  suggestedImprovements: ConstitutionRecommendation[];
}

export interface AuditEvent {
  time: string;
  type: AuditEventType;
  actor: string;
  target: string;
  detail: string;
}

export interface SettingsGroup {
  title: string;
  description: string;
  enabled: boolean;
}

export interface DetailSignal {
  label: string;
  value: string;
  tone: "neutral" | "success" | "warning" | "danger";
}

export interface ContextOSDesktopData {
  project: string;
  branch: string;
  repository: string;
  overview: OverviewMetrics;
  currentTask: CurrentTask;
  files: FileRecord[];
  scopeAnalysis: ScopeAnalysis;
  tokenUsage: TokenUsage;
  constitution: Constitution;
  auditLog: AuditEvent[];
  settings: SettingsGroup[];
  details: {
    finalDecision: string;
    confidence: string;
    trustSummary: string;
    signals: DetailSignal[];
  };
}

export interface ClassifierFinding {
  path: string;
  classification:
    | "intent_allowed"
    | "policy_allowed"
    | "review_required"
    | "blocked"
    | "default_review_required";
  confidence: "high" | "reduced" | "low";
  reason: string;
}

export interface ClassifierReport {
  contract: string;
  policy: string;
  base: string;
  changed_files: string[];
  findings: ClassifierFinding[];
  final_decision:
    | "BLOCKED"
    | "REVIEW_REQUIRED"
    | "POLICY_ALLOWED_WITH_REDUCED_CONFIDENCE"
    | "COMPLIANT";
  confidence: "LOW" | "REDUCED" | "HIGH";
  reason: string;
}
