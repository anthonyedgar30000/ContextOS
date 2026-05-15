import { NextResponse } from "next/server";
import { contextOverlayProtocolJsonSchema } from "@/lib/protocol";

export function GET() {
  return NextResponse.json(contextOverlayProtocolJsonSchema);
}
