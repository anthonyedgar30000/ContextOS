import { NextResponse } from "next/server";
import { z } from "zod";
import { buildCommandOverlay } from "@/lib/overlays";
import { modes, overlaySchema } from "@/lib/protocol";

export const runtime = "nodejs";

const commandSchema = z.object({
  command: z.string().trim().min(2),
  mode: z.enum(modes),
});

export async function POST(request: Request) {
  const body = await request.json();
  const parsed = commandSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  const overlay = overlaySchema.parse(buildCommandOverlay(parsed.data.command, parsed.data.mode));

  return NextResponse.json({ overlay });
}
