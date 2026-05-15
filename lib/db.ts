import Database from "better-sqlite3";
import { mkdirSync } from "fs";
import path from "path";
import { z } from "zod";
import { modes, type ContextMode } from "./protocol";

const dataDir = path.join(process.cwd(), "data");
const dbPath = path.join(dataDir, "contextos.sqlite");

mkdirSync(dataDir, { recursive: true });

const globalForDb = globalThis as unknown as {
  contextosDb?: Database.Database;
};

const db =
  globalForDb.contextosDb ??
  new Database(dbPath, {
    fileMustExist: false,
  });

if (process.env.NODE_ENV !== "production") {
  globalForDb.contextosDb = db;
}

db.pragma("journal_mode = WAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS profile (
    id TEXT PRIMARY KEY,
    overlay_density REAL NOT NULL,
    spoiler_mode INTEGER NOT NULL,
    preferred_mode TEXT NOT NULL,
    detail_level INTEGER NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS behavior_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    overlay_id TEXT,
    mode TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
  );
`);

const defaultProfile = {
  id: "local-user",
  overlayDensity: 0.72,
  spoilerMode: false,
  preferredMode: "Learning" as ContextMode,
  detailLevel: 2,
};

const now = () => new Date().toISOString();

db.prepare(
  `
  INSERT OR IGNORE INTO profile (
    id,
    overlay_density,
    spoiler_mode,
    preferred_mode,
    detail_level,
    updated_at
  ) VALUES (?, ?, ?, ?, ?, ?)
`,
).run(
  defaultProfile.id,
  defaultProfile.overlayDensity,
  defaultProfile.spoilerMode ? 1 : 0,
  defaultProfile.preferredMode,
  defaultProfile.detailLevel,
  now(),
);

const profileRowSchema = z.object({
  id: z.string(),
  overlay_density: z.number(),
  spoiler_mode: z.number(),
  preferred_mode: z.enum(modes),
  detail_level: z.number(),
  updated_at: z.string(),
});

export const profilePatchSchema = z.object({
  overlayDensity: z.number().min(0.15).max(1).optional(),
  spoilerMode: z.boolean().optional(),
  preferredMode: z.enum(modes).optional(),
  detailLevel: z.number().int().min(1).max(4).optional(),
});

export const behaviorEventSchema = z.object({
  eventType: z.enum(["overlay_opened", "overlay_dismissed", "useful_rating", "annoying_rating"]),
  overlayId: z.string().optional(),
  mode: z.enum(modes),
  payload: z.record(z.string(), z.unknown()).default({}),
});

export type UserProfile = {
  id: string;
  overlayDensity: number;
  spoilerMode: boolean;
  preferredMode: ContextMode;
  detailLevel: number;
  updatedAt: string;
};

export type BehaviorLog = {
  id: number;
  eventType: string;
  overlayId: string | null;
  mode: ContextMode;
  payload: Record<string, unknown>;
  createdAt: string;
};

function mapProfile(row: unknown): UserProfile {
  const parsed = profileRowSchema.parse(row);

  return {
    id: parsed.id,
    overlayDensity: parsed.overlay_density,
    spoilerMode: Boolean(parsed.spoiler_mode),
    preferredMode: parsed.preferred_mode,
    detailLevel: parsed.detail_level,
    updatedAt: parsed.updated_at,
  };
}

export function getProfile() {
  const row = db.prepare("SELECT * FROM profile WHERE id = ?").get(defaultProfile.id);
  return mapProfile(row);
}

export function updateProfile(patch: z.infer<typeof profilePatchSchema>) {
  const current = getProfile();
  const next = {
    ...current,
    ...patch,
    updatedAt: now(),
  };

  db.prepare(
    `
    UPDATE profile
    SET overlay_density = ?,
      spoiler_mode = ?,
      preferred_mode = ?,
      detail_level = ?,
      updated_at = ?
    WHERE id = ?
  `,
  ).run(
    next.overlayDensity,
    next.spoilerMode ? 1 : 0,
    next.preferredMode,
    next.detailLevel,
    next.updatedAt,
    current.id,
  );

  return getProfile();
}

function applyAdaptiveRules(eventType: string) {
  const profile = getProfile();

  if (eventType === "overlay_dismissed" || eventType === "annoying_rating") {
    updateProfile({
      overlayDensity: Math.max(0.15, Number((profile.overlayDensity - 0.08).toFixed(2))),
      detailLevel: Math.max(1, profile.detailLevel - (eventType === "annoying_rating" ? 1 : 0)),
    });
  }

  if (eventType === "useful_rating") {
    updateProfile({
      overlayDensity: Math.min(1, Number((profile.overlayDensity + 0.05).toFixed(2))),
      detailLevel: Math.min(4, profile.detailLevel + 1),
    });
  }
}

export function recordBehavior(input: z.infer<typeof behaviorEventSchema>) {
  const createdAt = now();

  db.prepare(
    `
    INSERT INTO behavior_logs (event_type, overlay_id, mode, payload, created_at)
    VALUES (?, ?, ?, ?, ?)
  `,
  ).run(input.eventType, input.overlayId ?? null, input.mode, JSON.stringify(input.payload), createdAt);

  applyAdaptiveRules(input.eventType);

  return {
    profile: getProfile(),
    log: {
      eventType: input.eventType,
      overlayId: input.overlayId ?? null,
      mode: input.mode,
      payload: input.payload,
      createdAt,
    },
  };
}

export function listBehaviorLogs(): BehaviorLog[] {
  const rows = db
    .prepare(
      `
      SELECT id,
        event_type as eventType,
        overlay_id as overlayId,
        mode,
        payload,
        created_at as createdAt
      FROM behavior_logs
      ORDER BY id DESC
      LIMIT 80
    `,
    )
    .all() as Array<{
    id: number;
    eventType: string;
    overlayId: string | null;
    mode: ContextMode;
    payload: string;
    createdAt: string;
  }>;

  return rows.map((row) => ({
    ...row,
    payload: JSON.parse(row.payload) as Record<string, unknown>,
  }));
}

export function getDebugState() {
  return {
    profile: getProfile(),
    logs: listBehaviorLogs(),
  };
}
