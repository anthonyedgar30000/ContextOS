import { NextResponse } from "next/server";
import { behaviorEventSchema, getDebugState, recordBehavior } from "@/lib/db";

export const runtime = "nodejs";

export function GET() {
  return NextResponse.json(getDebugState());
}

export async function POST(request: Request) {
  const body = await request.json();
  const parsed = behaviorEventSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  return NextResponse.json(recordBehavior(parsed.data));
}
