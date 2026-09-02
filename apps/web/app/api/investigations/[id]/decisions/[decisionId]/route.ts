import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; decisionId: string }> }
) {
  const { id, decisionId } = await params;
  const response = await backendFetch(`/v1/investigations/${id}/decisions/${decisionId}`);
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
