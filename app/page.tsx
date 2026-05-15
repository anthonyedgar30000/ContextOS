"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { modes, type ContextMode, type OverlayMessage } from "@/lib/protocol";

type UserProfile = {
  id: string;
  overlayDensity: number;
  spoilerMode: boolean;
  preferredMode: ContextMode;
  detailLevel: number;
  updatedAt: string;
};

type LogEvent = "overlay_opened" | "overlay_dismissed" | "useful_rating" | "annoying_rating";

const modeDescriptions: Record<ContextMode, string> = {
  Minimal: "Only critical contextual signals.",
  Movie: "Narrative-aware cues and scene beats.",
  Sports: "Momentum, plays, and defensive analogies.",
  Learning: "Expanded cyber explanations and evidence.",
};

const initialProfile: UserProfile = {
  id: "local-user",
  overlayDensity: 0.72,
  spoilerMode: false,
  preferredMode: "Learning",
  detailLevel: 2,
  updatedAt: "",
};

function densityLabel(value: number) {
  if (value < 0.35) return "Low";
  if (value < 0.75) return "Balanced";
  return "High";
}

export default function Home() {
  const [profile, setProfile] = useState<UserProfile>(initialProfile);
  const [mode, setMode] = useState<ContextMode>("Learning");
  const [overlays, setOverlays] = useState<OverlayMessage[]>([]);
  const [selectedOverlay, setSelectedOverlay] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [command, setCommand] = useState("");
  const [schemaPreview, setSchemaPreview] = useState<Record<string, unknown> | null>(null);
  const [isCommanding, setIsCommanding] = useState(false);

  const visibleOverlays = useMemo(
    () => overlays.filter((overlay) => !dismissed.has(overlay.id)),
    [dismissed, overlays],
  );

  const currentOverlay = visibleOverlays.find((overlay) => overlay.id === selectedOverlay) ?? visibleOverlays[0];

  async function refresh(nextMode = mode) {
    const response = await fetch(`/api/overlays?mode=${encodeURIComponent(nextMode)}`);
    const data = (await response.json()) as { overlays: OverlayMessage[]; profile: UserProfile };
    setProfile(data.profile);
    setMode(data.profile.preferredMode === nextMode ? data.profile.preferredMode : nextMode);
    setOverlays(data.overlays);
    setDismissed(new Set());
    setSelectedOverlay(data.overlays[0]?.id ?? null);
  }

  useEffect(() => {
    refresh("Learning").catch(console.error);
    fetch("/api/protocol")
      .then((response) => response.json())
      .then((data: Record<string, unknown>) => setSchemaPreview(data))
      .catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function updateProfile(patch: Partial<UserProfile>) {
    const response = await fetch("/api/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const nextProfile = (await response.json()) as UserProfile;
    setProfile(nextProfile);
    return nextProfile;
  }

  async function chooseMode(nextMode: ContextMode) {
    setMode(nextMode);
    await updateProfile({ preferredMode: nextMode });
    await refresh(nextMode);
  }

  async function record(eventType: LogEvent, overlay: OverlayMessage) {
    const response = await fetch("/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        eventType,
        overlayId: overlay.id,
        mode,
        payload: {
          title: overlay.title,
          detailLevel: profile.detailLevel,
          densityBefore: profile.overlayDensity,
        },
      }),
    });
    const data = (await response.json()) as { profile: UserProfile };
    setProfile(data.profile);
  }

  async function openOverlay(overlay: OverlayMessage) {
    setSelectedOverlay(overlay.id);
    await record("overlay_opened", overlay);
  }

  async function dismissOverlay(overlay: OverlayMessage) {
    setDismissed((current) => new Set(current).add(overlay.id));
    await record("overlay_dismissed", overlay);
  }

  async function rateOverlay(eventType: Extract<LogEvent, "useful_rating" | "annoying_rating">, overlay: OverlayMessage) {
    await record(eventType, overlay);
    await refresh(mode);
  }

  async function submitCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!command.trim()) return;

    setIsCommanding(true);
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, mode }),
    });
    const data = (await response.json()) as { overlay: OverlayMessage };
    setOverlays((current) => [data.overlay, ...current]);
    setSelectedOverlay(data.overlay.id);
    setCommand("");
    setIsCommanding(false);
  }

  return (
    <main className="min-h-screen overflow-hidden px-5 py-6 text-slate-100 sm:px-8 lg:px-12">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-xs uppercase tracking-[0.35em] text-cyan-200">
              ContextOS Capstone MVP
            </div>
            <h1 className="text-4xl font-black tracking-tight text-white sm:text-6xl">
              AI-native contextual media overlay
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
              A futuristic prototype that adapts timed cyber-intelligence cards over video using a local profile,
              behavior telemetry, and the Context Overlay Protocol.
            </p>
          </div>

          <Link
            href="/admin"
            className="glass-panel rounded-2xl px-5 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/60 hover:text-white"
          >
            Admin / debug dashboard
          </Link>
        </header>

        <section className="grid gap-5 lg:grid-cols-[1.45fr_0.55fr]">
          <div className="glass-panel relative overflow-hidden rounded-[2rem] p-3">
            <div className="absolute inset-0 scanline opacity-40" />
            <div className="relative aspect-video overflow-hidden rounded-[1.4rem] bg-slate-950">
              <video
                className="h-full w-full object-cover opacity-80"
                src="https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"
                controls
                loop
                muted
                autoPlay
              />
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-slate-950/75 via-transparent to-slate-950/55" />

              <div className="absolute left-4 top-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-3 py-1 text-xs font-bold text-emerald-200">
                  Live context stream
                </span>
                <span className="rounded-full border border-fuchsia-300/30 bg-fuchsia-300/10 px-3 py-1 text-xs font-bold text-fuchsia-100">
                  {mode} mode
                </span>
              </div>

              <div className="absolute bottom-4 left-4 right-4 grid gap-3 lg:grid-cols-[0.62fr_0.38fr]">
                <div className="rounded-2xl border border-cyan-200/25 bg-slate-950/72 p-4 shadow-2xl backdrop-blur-xl">
                  <div className="mb-2 flex items-center justify-between gap-4">
                    <p className="text-xs uppercase tracking-[0.28em] text-cyan-200">Active card</p>
                    <p className="text-xs text-slate-400">t+{currentOverlay?.timecode ?? 0}s</p>
                  </div>
                  <h2 className="text-2xl font-black text-white">{currentOverlay?.title ?? "Awaiting overlay"}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-200">{currentOverlay?.summary}</p>
                  {currentOverlay ? (
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      {profile.detailLevel > 1 ? currentOverlay.detail : currentOverlay.detail.split(".")[0]}
                    </p>
                  ) : null}
                </div>

                <div className="flex flex-col gap-2">
                  {visibleOverlays.slice(0, 3).map((overlay) => (
                    <button
                      key={overlay.id}
                      onClick={() => openOverlay(overlay)}
                      className={`pointer-events-auto rounded-2xl border p-3 text-left text-sm transition ${
                        selectedOverlay === overlay.id
                          ? "border-cyan-300/70 bg-cyan-300/15"
                          : "border-white/10 bg-slate-950/62 hover:border-cyan-300/40"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-white">{overlay.title}</span>
                        <span className="text-xs text-cyan-200">{Math.round(overlay.confidence * 100)}%</span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-300">{overlay.summary}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <aside className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.32em] text-cyan-200">Mode selector</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {modes.map((candidate) => (
                <button
                  key={candidate}
                  onClick={() => chooseMode(candidate)}
                  className={`rounded-2xl border px-3 py-3 text-left transition ${
                    mode === candidate
                      ? "border-cyan-300 bg-cyan-300/15 text-white"
                      : "border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/50"
                  }`}
                >
                  <span className="block text-sm font-black">{candidate}</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-400">{modeDescriptions[candidate]}</span>
                </button>
              ))}
            </div>

            <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
              <div className="flex items-center justify-between">
                <p className="font-bold text-white">Local adaptive profile</p>
                <span className="rounded-full bg-cyan-300/10 px-2 py-1 text-xs text-cyan-200">
                  {densityLabel(profile.overlayDensity)}
                </span>
              </div>
              <label className="mt-4 block text-xs uppercase tracking-[0.25em] text-slate-400">
                Overlay density
              </label>
              <input
                type="range"
                min="0.15"
                max="1"
                step="0.01"
                value={profile.overlayDensity}
                onChange={(event) => setProfile({ ...profile, overlayDensity: Number(event.target.value) })}
                onMouseUp={(event) => updateProfile({ overlayDensity: Number(event.currentTarget.value) })}
                className="mt-3 w-full accent-cyan-300"
              />
              <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
                <span>Detail level {profile.detailLevel}</span>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={profile.spoilerMode}
                    onChange={async (event) => {
                      const spoilerMode = event.target.checked;
                      await updateProfile({ spoilerMode });
                      await refresh(mode);
                    }}
                  />
                  Spoiler mode
                </label>
              </div>
            </div>

            <form onSubmit={submitCommand} className="mt-6">
              <label className="text-xs uppercase tracking-[0.32em] text-cyan-200">Ask the scene</label>
              <div className="mt-3 flex gap-2">
                <input
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  placeholder="Ask about IOC, MITRE mapping, next action..."
                  className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-cyan-300"
                />
                <button
                  type="submit"
                  disabled={isCommanding}
                  className="rounded-2xl bg-cyan-300 px-4 py-3 text-sm font-black text-slate-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Ask
                </button>
              </div>
            </form>
          </aside>
        </section>

        <section className="grid gap-5 lg:grid-cols-[0.6fr_0.4fr]">
          <div className="glass-panel rounded-[2rem] p-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.32em] text-cyan-200">Overlay controls</p>
                <h2 className="mt-2 text-2xl font-black text-white">Behavior feedback loop</h2>
              </div>
              <p className="max-w-md text-sm leading-6 text-slate-300">
                Dismissals and annoying ratings reduce frequency. Useful ratings increase detail and density.
              </p>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {visibleOverlays.map((overlay) => (
                <article key={overlay.id} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.25em] text-fuchsia-200">{overlay.kind}</p>
                      <h3 className="mt-2 text-lg font-black text-white">{overlay.title}</h3>
                    </div>
                    <span className="rounded-full bg-cyan-300/10 px-2 py-1 text-xs text-cyan-100">
                      P{overlay.priority}
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-300">{overlay.summary}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {overlay.tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-white/5 px-2 py-1 text-xs text-slate-300">
                        #{tag}
                      </span>
                    ))}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      onClick={() => openOverlay(overlay)}
                      className="rounded-xl border border-cyan-300/30 px-3 py-2 text-xs font-bold text-cyan-100 hover:bg-cyan-300/10"
                    >
                      Open
                    </button>
                    <button
                      onClick={() => dismissOverlay(overlay)}
                      className="rounded-xl border border-amber-300/30 px-3 py-2 text-xs font-bold text-amber-100 hover:bg-amber-300/10"
                    >
                      Dismiss
                    </button>
                    <button
                      onClick={() => rateOverlay("useful_rating", overlay)}
                      className="rounded-xl border border-emerald-300/30 px-3 py-2 text-xs font-bold text-emerald-100 hover:bg-emerald-300/10"
                    >
                      Useful
                    </button>
                    <button
                      onClick={() => rateOverlay("annoying_rating", overlay)}
                      className="rounded-xl border border-rose-300/30 px-3 py-2 text-xs font-bold text-rose-100 hover:bg-rose-300/10"
                    >
                      Annoying
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.32em] text-cyan-200">Protocol schema</p>
            <h2 className="mt-2 text-2xl font-black text-white">Context Overlay Protocol</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Each card is a typed JSON message with mode, timecode, confidence, evidence, actions, and spoiler flags.
            </p>
            <pre className="mt-4 max-h-96 overflow-auto rounded-2xl border border-white/10 bg-slate-950/80 p-4 text-xs leading-5 text-cyan-50">
              {JSON.stringify(schemaPreview ?? {}, null, 2)}
            </pre>
          </div>
        </section>
      </div>
    </main>
  );
}
