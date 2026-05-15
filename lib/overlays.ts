import type { ContextMode, OverlayMessage } from "./protocol";

const baseOverlays: OverlayMessage[] = [
  {
    id: "ioc-hash-pivot",
    protocol: "context-overlay-protocol",
    version: "0.1",
    mode: "Learning",
    kind: "threat-intel",
    priority: 5,
    timecode: 12,
    title: "Suspicious hash pivot detected",
    summary: "The analyst correlates a SHA-256 artifact with recent ransomware staging activity.",
    detail:
      "ContextOS links the hash to a known loader family and recommends pivoting into DNS, parent process, and first-seen telemetry before containment.",
    confidence: 0.91,
    tags: ["ioc", "ransomware", "triage"],
    spoiler: false,
    actions: [
      { label: "Explain pivot", command: "explain this hash pivot" },
      { label: "Show containment", command: "what should the analyst do next" },
    ],
    evidence: [
      {
        source: "Threat model",
        excerpt: "Hash reputation alone is weak; enrichment becomes useful when paired with process lineage.",
      },
    ],
  },
  {
    id: "lateral-movement",
    protocol: "context-overlay-protocol",
    version: "0.1",
    mode: "Movie",
    kind: "timeline",
    priority: 4,
    timecode: 33,
    title: "Narrative beat: lateral movement",
    summary: "The scene shifts from endpoint compromise to domain reconnaissance.",
    detail:
      "The command window implies discovery of privileged shares. In a real SOC workflow, this would trigger identity, network, and EDR correlation.",
    confidence: 0.84,
    tags: ["attack-chain", "identity", "soc"],
    spoiler: true,
    actions: [
      { label: "Map to MITRE", command: "map this scene to mitre tactics" },
      { label: "Reduce spoilers", command: "hide future plot hints" },
    ],
    evidence: [
      {
        source: "Scene context",
        excerpt: "Credential access is often followed by discovery and lateral movement.",
      },
    ],
  },
  {
    id: "sports-cyber-analogy",
    protocol: "context-overlay-protocol",
    version: "0.1",
    mode: "Sports",
    kind: "entity",
    priority: 3,
    timecode: 48,
    title: "Play-call analogy",
    summary: "The defender is changing coverage after seeing attacker formation.",
    detail:
      "Like a coordinator disguising coverage, adaptive security changes detection posture once attacker behavior reveals intent.",
    confidence: 0.78,
    tags: ["analogy", "defense", "adaptation"],
    spoiler: false,
    actions: [
      { label: "Give simpler analogy", command: "explain like sports commentary" },
      { label: "Show cyber equivalent", command: "translate this to incident response" },
    ],
    evidence: [
      {
        source: "Overlay heuristic",
        excerpt: "Sports mode reframes technical context as momentum, formations, and play calls.",
      },
    ],
  },
  {
    id: "minimal-risk-chip",
    protocol: "context-overlay-protocol",
    version: "0.1",
    mode: "Minimal",
    kind: "threat-intel",
    priority: 2,
    timecode: 64,
    title: "Risk spike",
    summary: "Privilege escalation indicators appear in this segment.",
    detail:
      "Minimal mode keeps the overlay compact while still surfacing the most relevant risk signal.",
    confidence: 0.8,
    tags: ["risk", "privilege"],
    spoiler: false,
    actions: [{ label: "Why it matters", command: "why is this a risk spike" }],
    evidence: [
      {
        source: "Detection cue",
        excerpt: "Administrative context plus unusual execution path increases severity.",
      },
    ],
  },
];

export function getSeedOverlays(mode: ContextMode, density: number, spoilerMode: boolean) {
  const modeOverlays = baseOverlays.filter(
    (overlay) => overlay.mode === mode || overlay.mode === "Learning" || mode === "Learning",
  );
  const visible = spoilerMode ? modeOverlays : modeOverlays.filter((overlay) => !overlay.spoiler);
  const limit = Math.max(1, Math.min(visible.length, Math.round(density * visible.length)));

  return visible
    .sort((a, b) => b.priority - a.priority)
    .slice(0, limit)
    .map((overlay) => ({
      ...overlay,
      mode,
      detail:
        density > 0.7
          ? overlay.detail
          : overlay.detail.split(".").slice(0, 1).join(".") || overlay.detail,
    }));
}

export function buildCommandOverlay(command: string, mode: ContextMode): OverlayMessage {
  const normalized = command.trim().toLowerCase();
  const isMitre = normalized.includes("mitre") || normalized.includes("tactic");
  const isNext = normalized.includes("next") || normalized.includes("contain");

  return {
    id: `command-${Date.now()}`,
    protocol: "context-overlay-protocol",
    version: "0.1",
    mode,
    kind: "command-answer",
    priority: 5,
    timecode: 74,
    title: isMitre ? "MITRE ATT&CK contextual map" : isNext ? "Suggested response path" : "Contextual answer",
    summary: isMitre
      ? "This moment maps to Discovery, Credential Access, and Lateral Movement."
      : isNext
        ? "Prioritize containment evidence before blocking to preserve investigation quality."
        : `Answering in ${mode} mode with current scene context.`,
    detail: isMitre
      ? "The overlay protocol would package each tactic as a timed card with confidence, evidence snippets, and optional analyst actions."
      : isNext
        ? "Collect process lineage, isolate the suspected host, verify identity activity, and document affected assets for the incident timeline."
        : "ContextOS combines video timecode, selected mode, local profile preferences, and behavior feedback to tailor the response.",
    confidence: 0.88,
    tags: ["command", "contextual-ai", mode.toLowerCase()],
    spoiler: false,
    actions: [
      { label: "Make concise", command: "summarize this in one sentence" },
      { label: "Add evidence", command: "show evidence for this answer" },
    ],
    evidence: [
      {
        source: "Local prototype context",
        excerpt: "Command overlays are generated from the active mode and current media segment.",
      },
    ],
  };
}
