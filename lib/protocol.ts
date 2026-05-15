import { z } from "zod";

export const modes = ["Minimal", "Movie", "Sports", "Learning"] as const;
export type ContextMode = (typeof modes)[number];

export const overlayKinds = [
  "threat-intel",
  "entity",
  "timeline",
  "learning",
  "command-answer",
] as const;

export const overlaySchema = z.object({
  id: z.string().min(1),
  protocol: z.literal("context-overlay-protocol"),
  version: z.literal("0.1"),
  mode: z.enum(modes),
  kind: z.enum(overlayKinds),
  priority: z.number().int().min(1).max(5),
  timecode: z.number().nonnegative(),
  title: z.string().min(1),
  summary: z.string().min(1),
  detail: z.string().min(1),
  confidence: z.number().min(0).max(1),
  tags: z.array(z.string()),
  spoiler: z.boolean(),
  actions: z.array(
    z.object({
      label: z.string(),
      command: z.string(),
    }),
  ),
  evidence: z.array(
    z.object({
      source: z.string(),
      excerpt: z.string(),
    }),
  ),
});

export type OverlayMessage = z.infer<typeof overlaySchema>;

export const contextOverlayProtocolJsonSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "Context Overlay Protocol Message",
  type: "object",
  required: [
    "id",
    "protocol",
    "version",
    "mode",
    "kind",
    "priority",
    "timecode",
    "title",
    "summary",
    "detail",
    "confidence",
    "tags",
    "spoiler",
    "actions",
    "evidence",
  ],
  properties: {
    id: { type: "string", minLength: 1 },
    protocol: { const: "context-overlay-protocol" },
    version: { const: "0.1" },
    mode: { enum: modes },
    kind: { enum: overlayKinds },
    priority: { type: "integer", minimum: 1, maximum: 5 },
    timecode: { type: "number", minimum: 0 },
    title: { type: "string", minLength: 1 },
    summary: { type: "string", minLength: 1 },
    detail: { type: "string", minLength: 1 },
    confidence: { type: "number", minimum: 0, maximum: 1 },
    tags: {
      type: "array",
      items: { type: "string" },
    },
    spoiler: { type: "boolean" },
    actions: {
      type: "array",
      items: {
        type: "object",
        required: ["label", "command"],
        properties: {
          label: { type: "string" },
          command: { type: "string" },
        },
      },
    },
    evidence: {
      type: "array",
      items: {
        type: "object",
        required: ["source", "excerpt"],
        properties: {
          source: { type: "string" },
          excerpt: { type: "string" },
        },
      },
    },
  },
} as const;
