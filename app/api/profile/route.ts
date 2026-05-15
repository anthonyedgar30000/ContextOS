import { NextResponse } from "next/server";
import { getProfile, profilePatchSchema, updateProfile } from "@/lib/db";

export const runtime = "nodejs";

export function GET() {
  return NextResponse.json(getProfile());
}

export async function PATCH(request: Request) {
  const body = await request.json();
  const parsed = profilePatchSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  return NextResponse.json(updateProfile(parsed.data));
}
