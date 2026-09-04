import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

// GET returns the single, idempotent REAL Razorpay TEST action tied to
// this specific decision_id -- 404 if none has been attempted for it yet
// (a normal, expected state, not an error). Mirrors the Phase 7
// decisions/[decisionId]/actions proxy exactly, one level over for Phase
// 10, Milestone 3. See app.domain.razorpay_action.get_action_for_decision.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; decisionId: string }> }
) {
  const { id, decisionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/decisions/${decisionId}/razorpay-action`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

// Bodyless POST -- the backend derives authorization entirely from
// investigation_id/decision_id in the URL and the persisted Phase 6
// decision; nothing from the client body is ever read (see
// app.domain.razorpay_action.run_razorpay_action). This is a REAL
// network call to Razorpay's TEST API when the decision is ALLOWED and a
// TEST-mode client is configured server-side -- never a sandbox
// simulation. 201 on first execution, 200 on an idempotent replay --
// both statuses are just relayed as-is.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; decisionId: string }> }
) {
  const { id, decisionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/decisions/${decisionId}/razorpay-action`,
    { method: "POST" }
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
