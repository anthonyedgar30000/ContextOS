export type FindingClassification =
  | "intent_allowed"
  | "policy_allowed"
  | "review_required"
  | "blocked"
  | "default_review_required";

export type Confidence = "high" | "reduced" | "low";

export interface ChangeFinding {
  path: string;
  classification: FindingClassification;
  confidence: Confidence;
  reason: string;
}

export interface AssuranceSummary {
  repository: string;
  branch: string;
  base: string;
  contractPath: string;
  policyPath: string;
  finalDecision: "COMPLIANT" | "REVIEW_REQUIRED" | "BLOCKED";
  confidence: "HIGH" | "REDUCED" | "LOW";
  reason: string;
  intentAllowedPaths: string[];
  policyFallbackPaths: string[];
  findings: ChangeFinding[];
}

export const assuranceSummary: AssuranceSummary = {
  repository: "ContextOS",
  branch: "feature/gui-desktop",
  base: "origin/main",
  contractPath: ".contextos/contracts/CTX-0001-contextos-readme-update.yaml",
  policyPath: ".contextos/policies/normalized-policy.example.yaml",
  finalDecision: "REVIEW_REQUIRED",
  confidence: "REDUCED",
  reason:
    "Most changes match the Intent Contract, but governance metadata requires policy fallback and human review.",
  intentAllowedPaths: ["README.md", "docs/"],
  policyFallbackPaths: [".contextos/contracts/", ".contextos/policies/"],
  findings: [
    {
      path: "README.md",
      classification: "intent_allowed",
      confidence: "high",
      reason: "matched Intent Contract allowed_paths",
    },
    {
      path: "docs/CAPSTONE.md",
      classification: "intent_allowed",
      confidence: "high",
      reason: "matched Intent Contract allowed_paths",
    },
    {
      path: "docs/POLICY_CONNECTORS.md",
      classification: "intent_allowed",
      confidence: "high",
      reason: "matched Intent Contract allowed_paths",
    },
    {
      path: ".contextos/contracts/CTX-0001-contextos-readme-update.yaml",
      classification: "review_required",
      confidence: "reduced",
      reason:
        "outside Intent Contract; matched repository policy review_required governance_metadata",
    },
    {
      path: ".contextos/policies/normalized-policy.example.yaml",
      classification: "review_required",
      confidence: "reduced",
      reason:
        "outside Intent Contract; matched repository policy review_required governance_metadata",
    },
  ],
};
