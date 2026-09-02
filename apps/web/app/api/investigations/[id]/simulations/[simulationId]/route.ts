import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; simulationId: string }> }
) {
  const { id, simulationId } = await params;
  const response = await backendFetch(`/v1/investigations/${id}/simulations/${simulationId}`);
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
