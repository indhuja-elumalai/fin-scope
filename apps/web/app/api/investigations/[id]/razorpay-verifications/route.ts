import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

// Append-only Razorpay TEST outcome-verification history across every
// razorpay action for this investigation, newest first. See
// app.domain.razorpay_verification.list_verifications.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/razorpay-verifications${request.nextUrl.search}`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
