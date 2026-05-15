"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ContextMode } from "@/lib/protocol";

type UserProfile = {
  id: string;
  overlayDensity: number;
  spoilerMode: boolean;
  preferredMode: ContextMode;
  detailLevel: number;
  updatedAt: string;
};

type BehaviorLog = {
  id: number;
  eventType: string;
  overlayId: string | null;
  mode: ContextMode;
  payload: Record<string, unknown>;
  createdAt: string;
};

type DebugState = {
  profile: UserProfile;
  logs: BehaviorLog[];
};

export default function AdminPage() {
  const [state, setState] = useState<DebugState | null>(null);

  async function load() {
    const response = await fetch("/api/logs");
    const data = (await response.json()) as DebugState;
    setState(data);
  }

  useEffect(() => {
    const initialLoad = window.setTimeout(() => load().catch(console.error), 0);
    const interval = window.setInterval(() => load().catch(console.error), 3500);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(interval);
    };
  }, []);

  const profile = state?.profile;

  return (
    <main className="min-h-screen px-5 py-6 text-slate-100 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-fuchsia-300/30 bg-fuchsia-300/10 px-3 py-1 text-xs uppercase tracking-[0.35em] text-fuchsia-100">
              Debug console
            </div>
            <h1 className="text-4xl font-black tracking-tight text-white sm:text-6xl">ContextOS telemetry</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
              Inspect local profile state, adaptive rule effects, and behavior logs captured by the overlay prototype.
            </p>
          </div>

          <Link
            href="/"
            className="glass-panel rounded-2xl px-5 py-3 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/60 hover:text-white"
          >
            Back to video player
          </Link>
        </header>

        <section className="mt-6 grid gap-5 lg:grid-cols-4">
          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-200">Preferred mode</p>
            <p className="mt-3 text-3xl font-black text-white">{profile?.preferredMode ?? "--"}</p>
          </div>
          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-200">Overlay density</p>
            <p className="mt-3 text-3xl font-black text-white">
              {profile ? `${Math.round(profile.overlayDensity * 100)}%` : "--"}
            </p>
          </div>
          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-200">Detail level</p>
            <p className="mt-3 text-3xl font-black text-white">{profile?.detailLevel ?? "--"}</p>
          </div>
          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.28em] text-cyan-200">Spoiler mode</p>
            <p className="mt-3 text-3xl font-black text-white">{profile?.spoilerMode ? "On" : "Off"}</p>
          </div>
        </section>

        <section className="mt-6 grid gap-5 lg:grid-cols-[0.38fr_0.62fr]">
          <div className="glass-panel rounded-[2rem] p-5">
            <p className="text-xs uppercase tracking-[0.32em] text-cyan-200">Current profile JSON</p>
            <pre className="mt-4 max-h-[34rem] overflow-auto rounded-2xl border border-white/10 bg-slate-950/80 p-4 text-xs leading-5 text-cyan-50">
              {JSON.stringify(profile ?? {}, null, 2)}
            </pre>
          </div>

          <div className="glass-panel rounded-[2rem] p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.32em] text-cyan-200">Behavior logs</p>
                <h2 className="mt-2 text-2xl font-black text-white">Adaptive signal stream</h2>
              </div>
              <button
                onClick={() => load()}
                className="rounded-2xl border border-cyan-300/30 px-4 py-2 text-sm font-bold text-cyan-100 hover:bg-cyan-300/10"
              >
                Refresh
              </button>
            </div>

            <div className="mt-5 overflow-hidden rounded-2xl border border-white/10">
              <table className="w-full border-collapse text-left text-sm">
                <thead className="bg-white/[0.06] text-xs uppercase tracking-[0.2em] text-slate-400">
                  <tr>
                    <th className="p-3">Event</th>
                    <th className="p-3">Overlay</th>
                    <th className="p-3">Mode</th>
                    <th className="p-3">Created</th>
                    <th className="p-3">Payload</th>
                  </tr>
                </thead>
                <tbody>
                  {state?.logs.length ? (
                    state.logs.map((log) => (
                      <tr key={log.id} className="border-t border-white/10 align-top">
                        <td className="p-3 font-bold text-cyan-100">{log.eventType}</td>
                        <td className="p-3 text-slate-300">{log.overlayId ?? "--"}</td>
                        <td className="p-3 text-slate-300">{log.mode}</td>
                        <td className="p-3 text-slate-400">{new Date(log.createdAt).toLocaleTimeString()}</td>
                        <td className="p-3">
                          <pre className="max-w-xs overflow-auto rounded-xl bg-slate-950/70 p-2 text-xs text-slate-300">
                            {JSON.stringify(log.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="p-5 text-slate-400" colSpan={5}>
                        No behavior events yet. Open, dismiss, or rate overlays on the video page.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
