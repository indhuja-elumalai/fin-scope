import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

// GET returns the single, idempotent Razorpay TEST outcome verification
// tied to this specific razorpay action_id -- 404 if this action has not
// been verified yet (a normal, expected state, not an error). See
// app.domain.razorpay_verification.get_verification_for_action.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; actionId: string }> }
) {
  const { id, actionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/razorpay-actions/${actionId}/verification`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

// Bodyless POST -- the backend derives everything from
// investigation_id/action_id in the URL and the persisted razorpay
// action / decision / simulation chain; nothing from the client body is
// ever read (see app.domain.razorpay_verification.run_razorpay_verification).
// OBSERVED here comes only from a real, already-ingested Razorpay webhook
// event -- never from Phase 5/7 or LLM output. 201 on first verification,
// 200 on an idempotent replay -- both statuses are just relayed as-is.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; actionId: string }> }
) {
  const { id, actionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/razorpay-actions/${actionId}/verification`,
    { method: "POST" }
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
