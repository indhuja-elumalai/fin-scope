import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/decisions${request.nextUrl.search}`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const response = await backendFetch(`/v1/investigations/${id}/decisions`, { method: "POST" });
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
