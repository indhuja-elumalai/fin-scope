import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const response = await backendFetch(`/v1/investigations/${id}/reason`, { method: "POST" });
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
