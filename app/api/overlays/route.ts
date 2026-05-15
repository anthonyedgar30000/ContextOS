import { NextResponse } from "next/server";
import { getProfile } from "@/lib/db";
import { getSeedOverlays } from "@/lib/overlays";
import { modes } from "@/lib/protocol";

export const runtime = "nodejs";

export function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const modeParam = searchParams.get("mode");
  const profile = getProfile();
  const mode = modes.find((candidate) => candidate === modeParam) ?? profile.preferredMode;
  const overlays = getSeedOverlays(mode, profile.overlayDensity, profile.spoilerMode);

  return NextResponse.json({
    overlays,
    profile,
  });
}
