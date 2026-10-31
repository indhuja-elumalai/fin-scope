import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/proxy";

// Append-only sandbox action history across every decision for this
// investigation, newest first. See app.domain.actions.list_actions.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/actions${request.nextUrl.search}`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
