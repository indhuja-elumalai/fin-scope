import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/backend";

// GET returns the single, idempotent outcome verification tied to this
// specific action_id -- 404 if this action has not been verified yet (a
// normal, expected state, not an error). See
// app.domain.verifications.get_verification_for_action.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; actionId: string }> }
) {
  const { id, actionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/actions/${actionId}/verification`
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

// Bodyless POST, mirroring the Phase 7 action-creation proxy -- the
// backend derives everything from investigation_id/action_id in the URL
// and the persisted action/decision/simulation chain; nothing from the
// client body is ever read (see app.domain.verifications.run_verification).
// 201 on first verification, 200 on an idempotent replay -- both statuses
// are just relayed as-is.
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; actionId: string }> }
) {
  const { id, actionId } = await params;
  const response = await backendFetch(
    `/v1/investigations/${id}/actions/${actionId}/verification`,
    { method: "POST" }
  );
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
