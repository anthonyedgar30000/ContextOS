import { invoke } from "@tauri-apps/api/core";
import type {
  ClassifierFinding,
  ClassifierReport,
  ContextOSDesktopData,
  FileStatus,
  RiskLevel,
} from "../types/contextos";

function statusForFinding(finding: ClassifierFinding): FileStatus {
  if (finding.classification === "blocked") {
    return "Blocked";
  }
  if (
    finding.classification === "review_required" ||
    finding.classification === "default_review_required"
  ) {
    return "Review Required";
  }
  return "Allowed";
}

function riskForFinding(finding: ClassifierFinding): RiskLevel {
  if (finding.classification === "blocked") {
    return "Critical";
  }
  if (finding.confidence === "low") {
    return "High";
  }
  if (finding.confidence === "reduced") {
    return "Medium";
  }
  return "Low";
}

function trustScoreForReport(report: ClassifierReport): number {
  if (report.final_decision === "BLOCKED") {
    return 38;
  }
  if (report.final_decision === "REVIEW_REQUIRED") {
    return 72;
  }
  if (report.final_decision === "POLICY_ALLOWED_WITH_REDUCED_CONFIDENCE") {
    return 84;
  }
  return 96;
}

function scopeDriftForReport(report: ClassifierReport): string {
  const hasFallback = report.findings.some(
    (finding) => finding.classification !== "intent_allowed",
  );
  return hasFallback ? "Moderate" : "None";
}

export async function fetchClassifierReport(): Promise<ClassifierReport> {
  const output = await invoke<string>("classify_changes");
  return JSON.parse(output) as ClassifierReport;
}

export function mergeClassifierReport(
  fallbackData: ContextOSDesktopData,
  report: ClassifierReport,
): ContextOSDesktopData {
  const files = report.findings.map((finding) => ({
    path: finding.path,
    status: statusForFinding(finding),
    risk: riskForFinding(finding),
    lastModified: "current diff",
  }));
  const trustScore = trustScoreForReport(report);
  const reviewRequiredCount = report.findings.filter(
    (finding) =>
      finding.classification === "review_required" ||
      finding.classification === "default_review_required",
  ).length;
  const blockedCount = report.findings.filter(
    (finding) => finding.classification === "blocked",
  ).length;

  return {
    ...fallbackData,
    overview: {
      ...fallbackData.overview,
      currentTask: "Classify repository changes",
      filesModified: report.changed_files.length,
      filesRead: Math.max(fallbackData.overview.filesRead, report.findings.length),
      scopeDrift: scopeDriftForReport(report),
      trustScore,
    },
    currentTask: {
      ...fallbackData.currentTask,
      userIntent:
        "Classify current repository changes against the active Intent Contract and normalized repository policy.",
      currentStatus: `${report.final_decision} (${report.confidence} confidence)`,
      timeline: [
        {
          time: "live",
          type: "verification",
          title: "Classifier refreshed",
          detail: `Read ${report.contract}, ${report.policy}, and compared ${report.base}..HEAD.`,
        },
        ...fallbackData.currentTask.timeline,
      ],
    },
    files,
    scopeAnalysis: {
      ...fallbackData.scopeAnalysis,
      observedScope: report.changed_files,
      scopeDriftScore: report.findings.some(
        (finding) => finding.classification !== "intent_allowed",
      )
        ? 24
        : 0,
      explanation: report.reason,
    },
    details: {
      ...fallbackData.details,
      finalDecision: report.final_decision,
      confidence: report.confidence,
      trustSummary: report.reason,
      signals: [
        {
          label: "Changed Files",
          value: String(report.changed_files.length),
          tone: "neutral",
        },
        {
          label: "Trust Score",
          value: `${trustScore} / 100`,
          tone: trustScore >= 80 ? "success" : "warning",
        },
        {
          label: "Review Required",
          value: String(reviewRequiredCount),
          tone: reviewRequiredCount > 0 ? "warning" : "success",
        },
        {
          label: "Blocked Paths",
          value: String(blockedCount),
          tone: blockedCount > 0 ? "danger" : "success",
        },
      ],
    },
  };
}
