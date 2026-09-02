import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

export async function GET(request: NextRequest) {
  const response = await backendFetch(`/v1/investigations${request.nextUrl.search}`);
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

export async function POST(request: NextRequest) {
  const requestBody = await request.text();
  const response = await backendFetch("/v1/investigations", {
    method: "POST",
    body: requestBody,
  });
  const responseBody = await response.json();
  return NextResponse.json(responseBody, { status: response.status });
}
