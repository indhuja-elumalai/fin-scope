import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

// GET returns the single, idempotent sandbox action tied to this specific
// decision_id -- 404 if no action has been attempted for it yet (a normal,
// expected state, not an error). See app.domain.actions.get_action_for_decision.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; decisionId: string }> }
) {
  const { id, decisionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/decisions/${decisionId}/actions`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

// Bodyless POST, mirroring the decision-creation proxy above -- the backend
// derives authorization entirely from investigation_id/decision_id in the
// URL and the persisted Phase 6 decision; nothing from the client body is
// ever read (see app.domain.actions.run_action). 201 on first execution,
// 200 on an idempotent replay -- both statuses are just relayed as-is.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; decisionId: string }> }
) {
  const { id, decisionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/decisions/${decisionId}/actions`,
    { method: "POST" }
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
