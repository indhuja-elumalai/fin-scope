"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorText,
  LoadingRow,
  SectionHeading,
  Select,
} from "@/components/ui";

type EvidenceItem = {
  event_id: string;
  event_type: string;
  source: string;
  external_reference: string | null;
  amount: string | number | null;
  currency: string | null;
  occurred_at: string;
};

type ImpactBreakdownItem = {
  currency: string;
  total_amount: string;
  event_count: number;
};

type Investigation = {
  id: string;
  merchant_id: string;
  window_start: string;
  window_end: string;
  incident_detected: boolean;
  evidence_event_count: number;
  event_type_counts: Record<string, number>;
  evidence: EvidenceItem[];
  dominant_signal_event_type: string | null;
  dominant_signal_share: string | null;
  impact_breakdown: ImpactBreakdownItem[];
  impact_amount_unknown_count: number;
  created_at: string;
};

type Confidence = "high" | "medium" | "low";

type Hypothesis = {
  hypothesis_id: string;
  rank: number;
  title: string;
  explanation: string;
  confidence: Confidence;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  uncertainty: string;
};

type ReasoningStatus =
  | "completed"
  | "insufficient_evidence"
  | "unavailable"
  | "invalid_output"
  | "no_valid_hypotheses";

type Reasoning = {
  id: string;
  investigation_id: string;
  status: ReasoningStatus;
  hypotheses: Hypothesis[];
  failure_reason: string | null;
  created_at: string;
};

type SimulationScenario =
  | "DO_NOTHING"
  | "RETRY_AFFECTED_PAYMENTS"
  | "REROUTE_PROVIDER"
  | "TARGET_AFFECTED_EVENT_TYPE";

type SimulationStatus = "completed" | "insufficient_evidence";

type SimulationCurrencyAmount = {
  currency: string;
  amount: string;
};

type SimulationScopeSnapshot = {
  failed_event_count: number;
  success_event_count: number;
  exposure_by_currency: SimulationCurrencyAmount[];
  exposure_amount_unknown_count: number;
};

type SimulationResultDetail = {
  scope_description: string;
  eligible_event_count: number;
  eligible_event_ids: string[];
  baseline: SimulationScopeSnapshot;
  projected: SimulationScopeSnapshot;
  estimated_recovery_by_currency: SimulationCurrencyAmount[];
  delta: {
    failed_event_count_delta: number;
    financial_delta_by_currency: SimulationCurrencyAmount[];
  };
};

type Simulation = {
  id: string;
  investigation_id: string;
  scenario: SimulationScenario;
  status: SimulationStatus;
  simulator_version: string;
  assumptions: { success_rate: string | null; scope_fraction: string | null };
  // {} when status !== "completed" -- see app.schemas.simulation.SimulationRead.
  result: SimulationResultDetail | Record<string, never>;
  failure_reason: string | null;
  created_at: string;
};

type DecisionStatus = "completed" | "insufficient_evidence" | "no_eligible_scenario";

type PolicyDecisionValue = "ALLOWED" | "REQUIRES_HUMAN_APPROVAL" | "BLOCKED";

type EvaluatedCandidate = {
  simulation_id: string;
  scenario: SimulationScenario;
  failed_event_count_delta: number;
  estimated_recovery_by_currency: SimulationCurrencyAmount[];
  // PROJECTED FINANCIAL EXPOSURE -- what policy thresholds actually apply
  // to, never estimated_recovery_by_currency (see app.domain.policy).
  projected_exposure_by_currency: SimulationCurrencyAmount[];
  projected_exposure_amount_unknown_count: number;
  eligible_event_count: number;
};

type EvaluationResultDetail = {
  candidates: EvaluatedCandidate[];
  preferred_scenario: SimulationScenario;
  preferred_simulation_id: string;
  reason: string;
};

type Decision = {
  id: string;
  investigation_id: string;
  status: DecisionStatus;
  evaluation_version: string;
  policy_version: string | null;
  candidate_simulation_ids: string[];
  // {} when status !== "completed" -- see app.schemas.decision.DecisionRead.
  evaluation_result: EvaluationResultDetail | Record<string, never>;
  policy_decision: PolicyDecisionValue | null;
  policy_reasons: string[];
  failure_reason: string | null;
  created_at: string;
};

// Phase 7 (bounded sandbox action). An Action is authorized by exactly one
// persisted Phase 6 decision (decision_id) -- never "the investigation's
// latest decision" -- and is idempotent per decision_id, unlike the
// append-only Reasoning/Simulation/Decision history above. See
// app.domain.actions and app.models.investigation_action for the contract
// this mirrors.
type ActionStatus = "executed" | "rejected";

type ActionCurrencyAmount = {
  currency: string;
  amount: string;
};

type SandboxResultDetail = {
  action_kind: string;
  targeted_event_ids: string[];
  targeted_event_count: number;
  simulated_outcome_by_currency: ActionCurrencyAmount[];
  note: string;
};

type Action = {
  id: string;
  investigation_id: string;
  decision_id: string;
  status: ActionStatus;
  rejection_reason: string | null;
  scenario: SimulationScenario | null;
  simulation_id: string | null;
  policy_decision_snapshot: PolicyDecisionValue | null;
  executor_version: string;
  // {} only in the unlikely case a legacy row predates a field -- in
  // practice every persisted action has a fully-populated sandbox_result.
  sandbox_result: SandboxResultDetail | Record<string, never>;
  created_at: string;
};

// Phase 8 (outcome verification). A Verification is anchored to exactly
// one persisted Phase 7 action (action_id) -- never "the investigation's
// latest action" -- and, like Action, is idempotent per action_id rather
// than append-only. EXPECTED comes from the action's own persisted Phase 5
// simulation (PROJECTED, never a live recalculation); OBSERVED is derived
// from the action's own persisted sandbox_result (SANDBOX, never a copy of
// EXPECTED) -- see app.domain.outcome_verification and
// app.domain.verifications for the full contract this mirrors.
type VerificationStatus =
  | "VERIFIED_SUCCESS"
  | "PARTIALLY_VERIFIED"
  | "FAILED"
  | "INSUFFICIENT_OBSERVATION";

type VerificationCurrencyAmount = {
  currency: string;
  amount: string;
};

// Unavailable shape: {"available": false, "reason": "..."}.
type ExpectedSnapshot =
  | {
      available: true;
      scenario: string;
      simulator_version: string;
      eligible_event_count: number | null;
      projected_success_count: number | null;
      projected_failure_count: number | null;
      projected_exposure_by_currency: VerificationCurrencyAmount[];
      estimated_recovery_by_currency: VerificationCurrencyAmount[];
    }
  | { available: false; reason: string };

type ObservedSnapshot =
  | {
      available: true;
      action_kind: string;
      observed_success_count: number | null;
      observed_failure_count: number | null;
      observed_recovery_by_currency: VerificationCurrencyAmount[];
      executor_version?: string;
    }
  | { available: false; reason: string };

type VerificationCountDimension = {
  expected: number | null;
  observed: number | null;
  match: boolean;
};

type VerificationRecoveryDimension = {
  expected: VerificationCurrencyAmount[];
  observed: VerificationCurrencyAmount[];
  match: boolean;
  missing_currencies: string[];
  unexpected_currencies: string[];
  amount_mismatches: string[];
};

type VerificationComparison = {
  status: VerificationStatus;
  verifier_version: string;
  dimensions:
    | {
        success_count: VerificationCountDimension;
        failure_count: VerificationCountDimension;
        recovery_by_currency: VerificationRecoveryDimension;
      }
    | Record<string, never>;
  matched_dimension_count: number;
  reasons: string[];
};

type Verification = {
  id: string;
  investigation_id: string;
  action_id: string;
  decision_id: string | null;
  simulation_id: string | null;
  status: VerificationStatus;
  verifier_version: string;
  expected_snapshot: ExpectedSnapshot;
  observed_snapshot: ObservedSnapshot;
  comparison: VerificationComparison;
  evidence: Record<string, unknown>;
  created_at: string;
};

const STATUS_COPY: Record<ReasoningStatus, { label: string; tone: "success" | "neutral" | "danger" }> = {
  completed: { label: "Reasoning complete", tone: "success" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "neutral" },
  unavailable: { label: "Reasoning unavailable", tone: "danger" },
  invalid_output: { label: "Reasoning output rejected", tone: "danger" },
  no_valid_hypotheses: { label: "No hypotheses proposed", tone: "neutral" },
};

const SCENARIO_LABELS: Record<SimulationScenario, string> = {
  DO_NOTHING: "Do nothing",
  RETRY_AFFECTED_PAYMENTS: "Retry affected payments",
  REROUTE_PROVIDER: "Reroute provider",
  TARGET_AFFECTED_EVENT_TYPE: "Target affected event type",
};

const SCENARIO_ORDER: SimulationScenario[] = [
  "DO_NOTHING",
  "RETRY_AFFECTED_PAYMENTS",
  "REROUTE_PROVIDER",
  "TARGET_AFFECTED_EVENT_TYPE",
];

const POLICY_COPY: Record<
  PolicyDecisionValue,
  { label: string; variant: "allowed" | "requires_approval" | "blocked" }
> = {
  ALLOWED: { label: "Allowed", variant: "allowed" },
  REQUIRES_HUMAN_APPROVAL: { label: "Requires human approval", variant: "requires_approval" },
  BLOCKED: { label: "Blocked", variant: "blocked" },
};

function decisionSummaryLabel(decision: Decision): string {
  if (decision.status === "insufficient_evidence") return "Insufficient evidence";
  if (decision.status === "no_eligible_scenario") return "No eligible scenario";
  if ("preferred_scenario" in decision.evaluation_result) {
    return SCENARIO_LABELS[decision.evaluation_result.preferred_scenario];
  }
  return "—";
}

// Phase 7: executed/rejected reuse the existing allowed/blocked colors --
// see the "sandbox" badge variant note in components/ui.tsx for why no new
// status colors were added.
const ACTION_STATUS_COPY: Record<ActionStatus, { label: string; variant: "allowed" | "blocked" }> = {
  executed: { label: "Executed", variant: "allowed" },
  rejected: { label: "Rejected", variant: "blocked" },
};

// Phase 8: reuses existing status colors -- allowed/requires_approval/
// blocked/neutral -- rather than adding four new ones, the same "only add
// the minimum badge variants required" discipline Phase 7 followed.
const VERIFICATION_STATUS_COPY: Record<
  VerificationStatus,
  { label: string; variant: "allowed" | "requires_approval" | "blocked" | "neutral" }
> = {
  VERIFIED_SUCCESS: { label: "Verified success", variant: "allowed" },
  PARTIALLY_VERIFIED: { label: "Partially verified", variant: "requires_approval" },
  FAILED: { label: "Failed", variant: "blocked" },
  INSUFFICIENT_OBSERVATION: { label: "Insufficient observation", variant: "neutral" },
};

function formatCurrencyAmounts(entries: VerificationCurrencyAmount[]): string {
  return entries.length > 0
    ? entries.map((item) => `${item.amount} ${item.currency}`).join(", ")
    : "—";
}

export default function InvestigationDetailPage() {
  const params = useParams<{ id: string }>();
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reasoning, setReasoning] = useState<Reasoning | null>(null);
  const [reasoningLoaded, setReasoningLoaded] = useState(false);
  const [reasoningRunning, setReasoningRunning] = useState(false);
  const [reasoningError, setReasoningError] = useState<string | null>(null);

  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [simulationsLoaded, setSimulationsLoaded] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState<SimulationScenario>("DO_NOTHING");
  const [simulationRunning, setSimulationRunning] = useState(false);
  const [simulationError, setSimulationError] = useState<string | null>(null);

  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [decisionsLoaded, setDecisionsLoaded] = useState(false);
  const [decisionRunning, setDecisionRunning] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // actionsHistory is the append-only history across ALL decisions for this
  // investigation (list_actions). actionForDecision is the single,
  // idempotent action tied to the CURRENT latest decision specifically
  // (get_action_for_decision) -- these are deliberately separate: an older
  // decision can still have its own action even after a newer decision
  // exists (see the MVP decision_id-anchor contract in app.domain.actions).
  const [actionsHistory, setActionsHistory] = useState<Action[]>([]);
  const [actionsLoaded, setActionsLoaded] = useState(false);
  const [actionForDecision, setActionForDecision] = useState<Action | null>(null);
  const [actionForDecisionLoaded, setActionForDecisionLoaded] = useState(false);
  const [actionRunning, setActionRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // verificationsHistory is the append-only history across ALL actions for
  // this investigation (list_verifications). verificationForAction is the
  // single, idempotent verification tied to the CURRENT latest action
  // specifically (get_verification_for_action) -- mirrors the
  // actionsHistory/actionForDecision split above exactly, one level down
  // the chain (action -> verification, not decision -> action).
  const [verificationsHistory, setVerificationsHistory] = useState<Verification[]>([]);
  const [verificationsLoaded, setVerificationsLoaded] = useState(false);
  const [verificationForAction, setVerificationForAction] = useState<Verification | null>(null);
  const [verificationForActionLoaded, setVerificationForActionLoaded] = useState(false);
  const [verificationRunning, setVerificationRunning] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/investigations/${params.id}`);
        if (response.status === 404) {
          throw new Error("Investigation not found.");
        }
        if (!response.ok) {
          throw new Error(`Failed to load investigation (${response.status})`);
        }
        const body = (await response.json()) as Investigation;
        if (!cancelled) setInvestigation(body);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load investigation.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads whatever reasoning result already exists, independent of the
  // investigation fetch above -- a 404 here just means "never run yet",
  // which is a normal, expected state, not an error to surface.
  useEffect(() => {
    let cancelled = false;

    async function loadReasoning() {
      try {
        const response = await fetch(`/api/investigations/${params.id}/reasoning`);
        if (response.status === 404) {
          if (!cancelled) setReasoning(null);
          return;
        }
        if (!response.ok) {
          throw new Error(`Failed to load reasoning (${response.status})`);
        }
        const body = (await response.json()) as Reasoning;
        if (!cancelled) setReasoning(body);
      } catch (err) {
        if (!cancelled) {
          setReasoningError(err instanceof Error ? err.message : "Failed to load reasoning.");
        }
      } finally {
        if (!cancelled) setReasoningLoaded(true);
      }
    }

    loadReasoning();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads existing simulation history, independent of investigation/reasoning --
  // a simulation never depends on reasoning having run (see
  // app.domain.simulation.run_simulation).
  useEffect(() => {
    let cancelled = false;

    async function loadSimulations() {
      try {
        const response = await fetch(`/api/investigations/${params.id}/simulations?limit=20`);
        if (!response.ok) {
          throw new Error(`Failed to load simulations (${response.status})`);
        }
        const body = (await response.json()) as { items: Simulation[] };
        if (!cancelled) setSimulations(body.items);
      } catch (err) {
        if (!cancelled) {
          setSimulationError(err instanceof Error ? err.message : "Failed to load simulations.");
        }
      } finally {
        if (!cancelled) setSimulationsLoaded(true);
      }
    }

    loadSimulations();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads existing decision history, independent of reasoning/simulation
  // loading above -- a decision reads whatever simulations already exist
  // at evaluation time (see app.domain.decisions.run_decision).
  useEffect(() => {
    let cancelled = false;

    async function loadDecisions() {
      try {
        const response = await fetch(`/api/investigations/${params.id}/decisions?limit=20`);
        if (!response.ok) {
          throw new Error(`Failed to load decisions (${response.status})`);
        }
        const body = (await response.json()) as { items: Decision[] };
        if (!cancelled) setDecisions(body.items);
      } catch (err) {
        if (!cancelled) {
          setDecisionError(err instanceof Error ? err.message : "Failed to load decisions.");
        }
      } finally {
        if (!cancelled) setDecisionsLoaded(true);
      }
    }

    loadDecisions();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads the append-only sandbox action history for this investigation,
  // independent of everything above -- an action reads whatever decision it
  // is tied to at execution time (see app.domain.actions.run_action).
  useEffect(() => {
    let cancelled = false;

    async function loadActionsHistory() {
      try {
        const response = await fetch(`/api/investigations/${params.id}/actions?limit=20`);
        if (!response.ok) {
          throw new Error(`Failed to load sandbox actions (${response.status})`);
        }
        const body = (await response.json()) as { items: Action[] };
        if (!cancelled) setActionsHistory(body.items);
      } catch (err) {
        if (!cancelled) {
          setActionError(err instanceof Error ? err.message : "Failed to load sandbox actions.");
        }
      } finally {
        if (!cancelled) setActionsLoaded(true);
      }
    }

    loadActionsHistory();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads the single idempotent action tied to the CURRENT latest decision
  // specifically (not "the latest action overall") -- re-fetches whenever a
  // new decision is evaluated. A 404 here just means "no sandbox action has
  // been attempted for this decision yet", a normal, expected state.
  const latestDecisionId = decisions[0]?.id ?? null;
  useEffect(() => {
    let cancelled = false;

    async function loadActionForDecision() {
      if (!latestDecisionId) {
        if (!cancelled) {
          setActionForDecision(null);
          setActionForDecisionLoaded(true);
        }
        return;
      }

      if (!cancelled) setActionForDecisionLoaded(false);

      try {
        const response = await fetch(
          `/api/investigations/${params.id}/decisions/${latestDecisionId}/actions`
        );
        if (response.status === 404) {
          if (!cancelled) setActionForDecision(null);
          return;
        }
        if (!response.ok) {
          throw new Error(`Failed to load sandbox action (${response.status})`);
        }
        const body = (await response.json()) as Action;
        if (!cancelled) setActionForDecision(body);
      } catch (err) {
        if (!cancelled) {
          setActionError(err instanceof Error ? err.message : "Failed to load sandbox action.");
        }
      } finally {
        if (!cancelled) setActionForDecisionLoaded(true);
      }
    }

    loadActionForDecision();
    return () => {
      cancelled = true;
    };
  }, [params.id, latestDecisionId]);

  // Loads the append-only outcome-verification history for this
  // investigation, independent of everything above -- a verification reads
  // whatever action it is tied to at verification time (see
  // app.domain.verifications.run_verification).
  useEffect(() => {
    let cancelled = false;

    async function loadVerificationsHistory() {
      try {
        const response = await fetch(`/api/investigations/${params.id}/verifications?limit=20`);
        if (!response.ok) {
          throw new Error(`Failed to load outcome verifications (${response.status})`);
        }
        const body = (await response.json()) as { items: Verification[] };
        if (!cancelled) setVerificationsHistory(body.items);
      } catch (err) {
        if (!cancelled) {
          setVerificationError(err instanceof Error ? err.message : "Failed to load outcome verifications.");
        }
      } finally {
        if (!cancelled) setVerificationsLoaded(true);
      }
    }

    loadVerificationsHistory();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // Loads the single idempotent verification tied to the CURRENT latest
  // action specifically -- re-fetches whenever a new action is attempted.
  // A 404 here just means "this action has not been verified yet", a
  // normal, expected state.
  const latestActionId = actionForDecision?.id ?? null;
  useEffect(() => {
    let cancelled = false;

    async function loadVerificationForAction() {
      if (!latestActionId) {
        if (!cancelled) {
          setVerificationForAction(null);
          setVerificationForActionLoaded(true);
        }
        return;
      }

      if (!cancelled) setVerificationForActionLoaded(false);

      try {
        const response = await fetch(
          `/api/investigations/${params.id}/actions/${latestActionId}/verification`
        );
        if (response.status === 404) {
          if (!cancelled) setVerificationForAction(null);
          return;
        }
        if (!response.ok) {
          throw new Error(`Failed to load outcome verification (${response.status})`);
        }
        const body = (await response.json()) as Verification;
        if (!cancelled) setVerificationForAction(body);
      } catch (err) {
        if (!cancelled) {
          setVerificationError(err instanceof Error ? err.message : "Failed to load outcome verification.");
        }
      } finally {
        if (!cancelled) setVerificationForActionLoaded(true);
      }
    }

    loadVerificationForAction();
    return () => {
      cancelled = true;
    };
  }, [params.id, latestActionId]);

  const runSimulation = useCallback(async () => {
    setSimulationRunning(true);
    setSimulationError(null);
    try {
      const response = await fetch(`/api/investigations/${params.id}/simulations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: selectedScenario }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to run simulation."
        );
      }
      const simulation = body as Simulation;
      setSimulations((prev) => [simulation, ...prev]);
    } catch (err) {
      setSimulationError(err instanceof Error ? err.message : "Failed to run simulation.");
    } finally {
      setSimulationRunning(false);
    }
  }, [params.id, selectedScenario]);

  const runReasoning = useCallback(async () => {
    setReasoningRunning(true);
    setReasoningError(null);
    try {
      const response = await fetch(`/api/investigations/${params.id}/reason`, {
        method: "POST",
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to run reasoning."
        );
      }
      setReasoning(body as Reasoning);
    } catch (err) {
      setReasoningError(err instanceof Error ? err.message : "Failed to run reasoning.");
    } finally {
      setReasoningRunning(false);
    }
  }, [params.id]);

  const runDecision = useCallback(async () => {
    setDecisionRunning(true);
    setDecisionError(null);
    try {
      const response = await fetch(`/api/investigations/${params.id}/decisions`, {
        method: "POST",
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to evaluate decision."
        );
      }
      setDecisions((prev) => [body as Decision, ...prev]);
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : "Failed to evaluate decision.");
    } finally {
      setDecisionRunning(false);
    }
  }, [params.id]);

  // Bodyless POST -- the server derives everything from investigation_id
  // and decision_id in the URL; the client supplies no authorization,
  // scenario, or outcome data (see app.domain.actions.run_action). Requires
  // a completed, ALLOWED latest decision; the button that calls this is
  // only rendered in that state (see SandboxActionSection), but the UI is
  // never the source of authorization -- the backend re-derives and
  // re-verifies everything regardless of what triggered the request.
  const runAction = useCallback(async () => {
    if (!latestDecisionId) return;
    setActionRunning(true);
    setActionError(null);
    try {
      const response = await fetch(
        `/api/investigations/${params.id}/decisions/${latestDecisionId}/actions`,
        { method: "POST" }
      );
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to execute sandbox action."
        );
      }
      const action = body as Action;
      setActionForDecision(action);
      setActionsHistory((prev) => (prev.some((a) => a.id === action.id) ? prev : [action, ...prev]));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to execute sandbox action.");
    } finally {
      setActionRunning(false);
    }
  }, [params.id, latestDecisionId]);

  // Bodyless POST -- the server derives everything from investigation_id
  // and action_id in the URL; the client supplies no expected value,
  // observed value, or verification status (see
  // app.domain.verifications.run_verification). Idempotent per action_id:
  // calling this again after a verification already exists just re-fetches
  // the same persisted result, never re-compares.
  const runVerification = useCallback(async () => {
    if (!latestActionId) return;
    setVerificationRunning(true);
    setVerificationError(null);
    try {
      const response = await fetch(
        `/api/investigations/${params.id}/actions/${latestActionId}/verification`,
        { method: "POST" }
      );
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to verify outcome."
        );
      }
      const verification = body as Verification;
      setVerificationForAction(verification);
      setVerificationsHistory((prev) =>
        prev.some((v) => v.id === verification.id) ? prev : [verification, ...prev]
      );
    } catch (err) {
      setVerificationError(err instanceof Error ? err.message : "Failed to verify outcome.");
    } finally {
      setVerificationRunning(false);
    }
  }, [params.id, latestActionId]);

  return (
    <main className="max-w-3xl mx-auto px-6 py-10">
      <Link
        href="/investigations"
        className="text-sm text-slate-500 hover:text-slate-900 transition-colors"
      >
        ← All investigations
      </Link>

      {loading && <div className="mt-4"><LoadingRow>Loading investigation…</LoadingRow></div>}
      {error && <div className="mt-4"><ErrorText>{error}</ErrorText></div>}

      {investigation && (
        <div className="mt-4 space-y-6">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                Investigation
              </p>
              <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2 mt-0.5">
                {investigation.incident_detected ? "Incident detected" : "No incident"}
                <Badge variant="fact">FACT</Badge>
              </h1>
            </div>
            <span className="text-xs text-slate-400 font-mono">{investigation.id}</span>
          </div>

          {/* 1. Incident */}
          <Card>
            <dl className="divide-y divide-slate-100">
              <div className="px-4 py-3 flex justify-between gap-4 text-sm">
                <dt className="text-slate-500">Merchant</dt>
                <dd className="text-right break-all font-mono text-xs text-slate-700 pt-0.5">
                  {investigation.merchant_id}
                </dd>
              </div>
              <div className="px-4 py-3 flex justify-between gap-4 text-sm">
                <dt className="text-slate-500">Window</dt>
                <dd className="text-right text-slate-900">
                  {new Date(investigation.window_start).toLocaleString()} –{" "}
                  {new Date(investigation.window_end).toLocaleString()}
                </dd>
              </div>
              <div className="px-4 py-3 flex justify-between gap-4 text-sm">
                <dt className="text-slate-500">Evidence event count</dt>
                <dd className="text-right text-slate-900 font-medium">
                  {investigation.evidence_event_count}
                </dd>
              </div>
            </dl>
          </Card>

          {/* 2. Dominant signal */}
          <Card className="p-4">
            <SectionHeading eyebrow="Deterministic heuristic" title="Dominant signal">
              <Badge variant="fact">FACT</Badge>
            </SectionHeading>
            <p className="text-sm text-slate-600 mt-2">
              {investigation.dominant_signal_event_type
                ? (
                  <>
                    <span className="font-medium text-slate-900">
                      &ldquo;{investigation.dominant_signal_event_type}&rdquo;
                    </span>{" "}
                    recurred most often —{" "}
                    <span className="font-medium text-slate-900">
                      {(Number(investigation.dominant_signal_share) * 100).toFixed(0)}%
                    </span>{" "}
                    of the evidence in this window.
                  </>
                )
                : "No dominant signal — insufficient evidence in this window."}
            </p>
            <p className="text-xs text-slate-400 mt-2">
              A frequency heuristic over observed events, not a causal finding.
            </p>
          </Card>

          {/* 3. Impact */}
          <Card className="p-4">
            <SectionHeading eyebrow="Currency-safe" title="Financial impact">
              <Badge variant="fact">FACT</Badge>
            </SectionHeading>
            {investigation.impact_breakdown.length === 0 ? (
              <p className="text-sm text-slate-500 mt-2">No amounts recorded for this evidence.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {investigation.impact_breakdown.map((item) => (
                  <li
                    key={item.currency}
                    className="flex items-baseline justify-between text-sm border-b border-slate-100 last:border-0 pb-2 last:pb-0"
                  >
                    <span className="text-slate-500">
                      {item.event_count} event{item.event_count === 1 ? "" : "s"}
                    </span>
                    <span className="font-semibold text-slate-900 tabular-nums">
                      {item.total_amount} {item.currency}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {investigation.impact_amount_unknown_count > 0 && (
              <p className="text-xs text-slate-400 mt-3">
                {investigation.impact_amount_unknown_count} evidence event
                {investigation.impact_amount_unknown_count === 1 ? "" : "s"} had no recorded amount
                and were excluded from the totals above.
              </p>
            )}
          </Card>

          {/* 4. Evidence */}
          <Card className="p-4">
            <SectionHeading eyebrow="Observed" title="Evidence timeline">
              <Badge variant="fact">FACT</Badge>
            </SectionHeading>
            {investigation.evidence.length === 0 ? (
              <p className="text-sm text-slate-500 mt-2">No evidence events in this window.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-100">
                {investigation.evidence.map((item) => (
                  <li
                    key={item.event_id}
                    id={`evidence-${item.event_id}`}
                    className="py-2.5 flex justify-between items-center text-sm scroll-mt-20"
                  >
                    <div>
                      <Link
                        href={`/events/${item.event_id}`}
                        className="font-medium text-slate-900 hover:text-blue-600 transition-colors"
                      >
                        {item.event_type}
                      </Link>
                      <div className="text-slate-400 text-xs mt-0.5">
                        {item.source} · {new Date(item.occurred_at).toLocaleString()}
                      </div>
                    </div>
                    <span className="text-slate-500 text-xs tabular-nums">
                      {item.amount ? `${item.amount} ${item.currency ?? ""}` : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* 5/6/7. Reasoning + hypotheses + uncertainty */}
          <ReasoningSection
            reasoning={reasoning}
            reasoningLoaded={reasoningLoaded}
            running={reasoningRunning}
            error={reasoningError}
            onRun={runReasoning}
          />

          {/* 8. Deterministic consequence simulation */}
          <SimulationSection
            simulations={simulations}
            simulationsLoaded={simulationsLoaded}
            running={simulationRunning}
            error={simulationError}
            selectedScenario={selectedScenario}
            onSelectScenario={setSelectedScenario}
            onRun={runSimulation}
          />

          {/* 9. Decision evaluation + policy */}
          <DecisionSection
            decisions={decisions}
            decisionsLoaded={decisionsLoaded}
            running={decisionRunning}
            error={decisionError}
            onRun={runDecision}
          />

          {/* 10. Bounded sandbox action -- authorized ONLY by the latest
              persisted, completed, ALLOWED decision. Never a source of
              authorization itself; see runAction above. */}
          <SandboxActionSection
            latestDecision={decisions[0] ?? null}
            actionForDecision={actionForDecision}
            actionForDecisionLoaded={actionForDecisionLoaded}
            actionsHistory={actionsHistory}
            actionsLoaded={actionsLoaded}
            running={actionRunning}
            error={actionError}
            onRun={runAction}
          />

          {/* 11. Outcome verification (Phase 8) -- anchored ONLY to the
              latest persisted, executed sandbox action. Never a source of
              expected/observed/authorization data itself; see
              runVerification above. */}
          <OutcomeVerificationSection
            latestAction={actionForDecision}
            verificationForAction={verificationForAction}
            verificationForActionLoaded={verificationForActionLoaded}
            verificationsHistory={verificationsHistory}
            verificationsLoaded={verificationsLoaded}
            running={verificationRunning}
            error={verificationError}
            onRun={runVerification}
          />
        </div>
      )}
    </main>
  );
}

function ReasoningSection({
  reasoning,
  reasoningLoaded,
  running,
  error,
  onRun,
}: {
  reasoning: Reasoning | null;
  reasoningLoaded: boolean;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  return (
    <Card className="p-4">
      <SectionHeading eyebrow="Investigation reasoning" title="Reasoning">
        <Badge variant="inference">INFERENCE</Badge>
      </SectionHeading>
      <p className="text-xs text-slate-400 mt-2">
        Evidence-grounded hypotheses proposed over the facts above — plausible explanations, not a
        confirmed root cause. Every citation below is checked against this investigation&apos;s
        own evidence before it is ever shown.
      </p>

      <div className="mt-4">
        {!reasoningLoaded && <LoadingRow>Checking for existing reasoning…</LoadingRow>}

        {reasoningLoaded && !reasoning && !running && (
          <EmptyState>Reasoning has not been run for this investigation yet.</EmptyState>
        )}

        {running && <div className="mt-1"><LoadingRow>Running reasoning…</LoadingRow></div>}

        {!running && reasoning && <ReasoningResult reasoning={reasoning} />}

        {error && <div className="mt-3"><ErrorText>{error}</ErrorText></div>}

        {!running && reasoningLoaded && (
          <div className="mt-4">
            <Button variant="secondary" onClick={onRun} disabled={running}>
              {reasoning ? "Re-run reasoning" : "Run reasoning"}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function ReasoningResult({ reasoning }: { reasoning: Reasoning }) {
  const copy = STATUS_COPY[reasoning.status];

  if (reasoning.status !== "completed") {
    return (
      <div className="space-y-2">
        <Badge variant={copy.tone}>{copy.label}</Badge>
        <p className="text-sm text-slate-600">
          {reasoning.status === "insufficient_evidence" &&
            "No incident was detected for this investigation, so there is no evidence pattern to reason about yet."}
          {reasoning.status === "no_valid_hypotheses" &&
            "The evidence in this window was too sparse or ambiguous to support a confident hypothesis."}
          {(reasoning.status === "unavailable" || reasoning.status === "invalid_output") &&
            (reasoning.failure_reason ?? "Reasoning could not produce a result.")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Badge variant="success">{copy.label}</Badge>
      <ol className="space-y-3">
        {reasoning.hypotheses.map((h) => (
          <HypothesisCard key={h.hypothesis_id} hypothesis={h} />
        ))}
      </ol>
    </div>
  );
}

function HypothesisCard({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <li className="border border-slate-200 rounded-lg p-3.5 bg-slate-50/50">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-semibold text-slate-400 tabular-nums">
            #{hypothesis.rank}
          </span>
          <h3 className="text-sm font-semibold text-slate-900">{hypothesis.title}</h3>
        </div>
        <Badge variant={hypothesis.confidence}>{hypothesis.confidence} confidence</Badge>
      </div>
      <p className="text-sm text-slate-600 mt-2">{hypothesis.explanation}</p>

      <div className="mt-3 grid sm:grid-cols-2 gap-3">
        <EvidenceRefList label="Supporting evidence" ids={hypothesis.supporting_evidence} />
        <EvidenceRefList label="Contradicting evidence" ids={hypothesis.contradicting_evidence} />
      </div>

      {hypothesis.uncertainty && (
        <div className="mt-3 flex items-start gap-1.5">
          <Badge variant="uncertainty">UNCERTAINTY</Badge>
          <p className="text-xs text-slate-500 flex-1">{hypothesis.uncertainty}</p>
        </div>
      )}
    </li>
  );
}

function EvidenceRefList({ label, ids }: { label: string; ids: string[] }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-400 mb-1">{label}</p>
      {ids.length === 0 ? (
        <p className="text-xs text-slate-400">None</p>
      ) : (
        <ul className="space-y-0.5">
          {ids.map((id) => (
            <li key={id}>
              <a href={`#evidence-${id}`} className="text-xs text-blue-600 hover:underline font-mono">
                {id.slice(0, 8)}…
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SimulationSection({
  simulations,
  simulationsLoaded,
  running,
  error,
  selectedScenario,
  onSelectScenario,
  onRun,
}: {
  simulations: Simulation[];
  simulationsLoaded: boolean;
  running: boolean;
  error: string | null;
  selectedScenario: SimulationScenario;
  onSelectScenario: (scenario: SimulationScenario) => void;
  onRun: () => void;
}) {
  const latest = simulations[0] ?? null;
  const history = simulations.slice(1);

  return (
    <Card className="p-4">
      <SectionHeading eyebrow="Scenario simulation" title="Consequence simulation">
        <Badge variant="projected">PROJECTED</Badge>
      </SectionHeading>
      <p className="text-xs text-slate-400 mt-2">
        Deterministic software calculates every number below from this investigation&apos;s own
        evidence — no AI/LLM is involved in the calculation. A projected result is a simulated
        consequence, never an actual financial outcome, and currencies are never mixed together.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="w-64">
          <Select
            aria-label="Scenario"
            value={selectedScenario}
            onChange={(e) => onSelectScenario(e.target.value as SimulationScenario)}
            disabled={running}
          >
            {SCENARIO_ORDER.map((scenario) => (
              <option key={scenario} value={scenario}>
                {SCENARIO_LABELS[scenario]}
              </option>
            ))}
          </Select>
        </div>
        <Button variant="secondary" onClick={onRun} disabled={running}>
          {running ? "Running simulation…" : "Run simulation"}
        </Button>
      </div>

      {error && <div className="mt-3"><ErrorText>{error}</ErrorText></div>}

      <div className="mt-4">
        {!simulationsLoaded && <LoadingRow>Loading simulation history…</LoadingRow>}
        {simulationsLoaded && !latest && !running && (
          <EmptyState>No simulation has been run for this investigation yet.</EmptyState>
        )}
        {running && <div className="mt-1"><LoadingRow>Running simulation…</LoadingRow></div>}
        {!running && latest && <SimulationResult simulation={latest} />}
      </div>

      {history.length > 0 && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
            Simulation history
          </p>
          <ul className="divide-y divide-slate-100">
            {history.map((simulation) => (
              <li key={simulation.id} className="py-2 flex items-center justify-between text-xs">
                <span className="text-slate-700 font-medium">
                  {SCENARIO_LABELS[simulation.scenario]}
                </span>
                <span className="text-slate-400">
                  {simulation.status === "completed"
                    ? `${simulation.result && "delta" in simulation.result ? simulation.result.delta.failed_event_count_delta : 0} failed-event delta`
                    : "insufficient evidence"}
                </span>
                <span className="text-slate-400 font-mono">
                  {new Date(simulation.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function SimulationResult({ simulation }: { simulation: Simulation }) {
  if (simulation.status !== "completed" || !("delta" in simulation.result)) {
    return (
      <div className="space-y-2">
        <Badge variant="neutral">Insufficient evidence</Badge>
        <p className="text-sm text-slate-600">
          {simulation.failure_reason ??
            "No incident was detected for this investigation, so there is nothing to simulate a consequence over yet."}
        </p>
      </div>
    );
  }

  const result = simulation.result;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className="text-sm font-semibold text-slate-900">
          {SCENARIO_LABELS[simulation.scenario]}
        </span>
        <span className="text-xs text-slate-400 font-mono">
          simulator v{simulation.simulator_version}
        </span>
      </div>
      <p className="text-xs text-slate-500">{result.scope_description}</p>

      <div className="flex items-center gap-1.5">
        <Badge variant="assumption">ASSUMPTION</Badge>
        <p className="text-xs text-slate-500">
          {simulation.assumptions.success_rate !== null
            ? `success rate ${simulation.assumptions.success_rate}, scope ${simulation.assumptions.scope_fraction} of ${result.eligible_event_count} eligible event${result.eligible_event_count === 1 ? "" : "s"}`
            : "no intervention applied"}
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        <SimulationScopeCard label="Baseline" tone="fact" scope={result.baseline} />
        <SimulationScopeCard label="Projected" tone="projected" scope={result.projected} />
      </div>

      {result.estimated_recovery_by_currency.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-400 mb-1">Estimated recovery</p>
          <ul className="space-y-1">
            {result.estimated_recovery_by_currency.map((item) => (
              <li key={item.currency} className="text-sm text-emerald-700 font-medium tabular-nums">
                {item.amount} {item.currency}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-xs font-medium text-slate-400 mb-1">
          Delta (projected − baseline)
        </p>
        <p className="text-sm text-slate-700">
          {result.delta.failed_event_count_delta} failed events
          {result.delta.financial_delta_by_currency.length > 0 && (
            <>
              {" · "}
              {result.delta.financial_delta_by_currency
                .map((item) => `${item.amount} ${item.currency}`)
                .join(", ")}
            </>
          )}
        </p>
      </div>
    </div>
  );
}

function SimulationScopeCard({
  label,
  tone,
  scope,
}: {
  label: string;
  tone: "fact" | "projected";
  scope: SimulationScopeSnapshot;
}) {
  return (
    <div className="border border-slate-200 rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-slate-500">{label}</span>
        <Badge variant={tone}>{tone === "fact" ? "FACT" : "PROJECTED"}</Badge>
      </div>
      <dl className="space-y-1 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-500">Failed</dt>
          <dd className="text-slate-900 font-medium tabular-nums">{scope.failed_event_count}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Succeeded</dt>
          <dd className="text-slate-900 font-medium tabular-nums">{scope.success_event_count}</dd>
        </div>
        {scope.exposure_by_currency.map((item) => (
          <div key={item.currency} className="flex justify-between">
            <dt className="text-slate-500">Exposure ({item.currency})</dt>
            <dd className="text-slate-900 font-medium tabular-nums">{item.amount}</dd>
          </div>
        ))}
        {scope.exposure_amount_unknown_count > 0 && (
          <p className="text-xs text-slate-400 pt-1">
            {scope.exposure_amount_unknown_count} event
            {scope.exposure_amount_unknown_count === 1 ? "" : "s"} with no recorded amount
            (excluded above).
          </p>
        )}
      </dl>
    </div>
  );
}

function DecisionSection({
  decisions,
  decisionsLoaded,
  running,
  error,
  onRun,
}: {
  decisions: Decision[];
  decisionsLoaded: boolean;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  const latest = decisions[0] ?? null;
  const history = decisions.slice(1);

  return (
    <Card className="p-4">
      <SectionHeading eyebrow="Deterministic comparison + policy" title="Decision evaluation">
        <Badge variant="decision">DECISION</Badge>
      </SectionHeading>
      <p className="text-xs text-slate-400 mt-2">
        Compares this investigation&apos;s own latest completed simulation per scenario — no
        AI/LLM is involved in either step. Evaluation picks a preferred scenario; policy then
        decides, independently, whether FIN-SCOPE may choose it. A preferred scenario can still be
        blocked. Phase 6 never executes an action.
      </p>

      <div className="mt-4">
        <Button variant="secondary" onClick={onRun} disabled={running}>
          {running ? "Evaluating…" : decisions.length > 0 ? "Re-evaluate" : "Evaluate scenarios"}
        </Button>
      </div>

      {error && (
        <div className="mt-3">
          <ErrorText>{error}</ErrorText>
        </div>
      )}

      <div className="mt-4">
        {!decisionsLoaded && <LoadingRow>Loading decision history…</LoadingRow>}
        {decisionsLoaded && !latest && !running && (
          <EmptyState>No decision has been evaluated for this investigation yet.</EmptyState>
        )}
        {running && (
          <div className="mt-1">
            <LoadingRow>Evaluating…</LoadingRow>
          </div>
        )}
        {!running && latest && <DecisionResult decision={latest} />}
      </div>

      {history.length > 0 && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
            Decision history
          </p>
          <ul className="divide-y divide-slate-100">
            {history.map((decision) => (
              <li key={decision.id} className="py-2 flex items-center justify-between text-xs">
                <span className="text-slate-700 font-medium">{decisionSummaryLabel(decision)}</span>
                <span className="text-slate-400">{decision.policy_decision ?? "—"}</span>
                <span className="text-slate-400 font-mono">
                  {new Date(decision.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function DecisionResult({ decision }: { decision: Decision }) {
  if (decision.status !== "completed" || !("preferred_scenario" in decision.evaluation_result)) {
    return (
      <div className="space-y-2">
        <Badge variant="neutral">
          {decision.status === "insufficient_evidence"
            ? "Insufficient evidence"
            : "No eligible scenario"}
        </Badge>
        <p className="text-sm text-slate-600">
          {decision.failure_reason ?? "There is nothing to evaluate a decision over yet."}
        </p>
      </div>
    );
  }

  const evaluation = decision.evaluation_result;
  const policyCopy = decision.policy_decision ? POLICY_COPY[decision.policy_decision] : null;

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
          Candidates compared
        </p>
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm min-w-[440px]">
            <thead>
              <tr className="text-left text-xs text-slate-400">
                <th className="font-medium pb-1.5 px-1">Scenario</th>
                <th className="font-medium pb-1.5 px-1 text-right">Failed Δ</th>
                <th className="font-medium pb-1.5 px-1 text-right">Recovery</th>
                <th className="font-medium pb-1.5 px-1 text-right">Exposure</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {evaluation.candidates.map((candidate) => (
                <tr
                  key={candidate.simulation_id}
                  className={
                    candidate.scenario === evaluation.preferred_scenario ? "bg-sky-50/60" : undefined
                  }
                >
                  <td className="py-1.5 px-1 text-slate-900 font-medium">
                    {SCENARIO_LABELS[candidate.scenario]}
                    {candidate.scenario === evaluation.preferred_scenario && (
                      <span className="ml-1.5 text-sky-600 text-xs font-normal">preferred</span>
                    )}
                  </td>
                  <td className="py-1.5 px-1 text-right tabular-nums text-slate-700">
                    {candidate.failed_event_count_delta}
                  </td>
                  <td className="py-1.5 px-1 text-right tabular-nums text-slate-700">
                    {candidate.estimated_recovery_by_currency.length > 0
                      ? candidate.estimated_recovery_by_currency
                          .map((item) => `${item.amount} ${item.currency}`)
                          .join(", ")
                      : "—"}
                  </td>
                  <td className="py-1.5 px-1 text-right tabular-nums text-slate-700">
                    {candidate.projected_exposure_by_currency.length > 0
                      ? candidate.projected_exposure_by_currency
                          .map((item) => `${item.amount} ${item.currency}`)
                          .join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="border border-slate-200 rounded-lg p-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant="decision">DECISION</Badge>
          <span className="text-sm font-semibold text-slate-900">
            Preferred: {SCENARIO_LABELS[evaluation.preferred_scenario]}
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-1.5">{evaluation.reason}</p>
      </div>

      {policyCopy && (
        <div className="border border-slate-200 rounded-lg p-3">
          <div className="flex items-center gap-1.5 flex-wrap">
            <Badge variant="neutral">POLICY</Badge>
            <Badge variant={policyCopy.variant}>{policyCopy.label}</Badge>
          </div>
          {decision.policy_reasons.length > 0 && (
            <ul className="mt-2 space-y-1">
              {decision.policy_reasons.map((reason) => (
                <li key={reason} className="text-xs text-slate-500">
                  {reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function SandboxActionSection({
  latestDecision,
  actionForDecision,
  actionForDecisionLoaded,
  actionsHistory,
  actionsLoaded,
  running,
  error,
  onRun,
}: {
  latestDecision: Decision | null;
  actionForDecision: Action | null;
  actionForDecisionLoaded: boolean;
  actionsHistory: Action[];
  actionsLoaded: boolean;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  // actionsHistory already includes actionForDecision (list_actions is a
  // superset of get_action_for_decision) -- avoid rendering it twice.
  const history = actionForDecision
    ? actionsHistory.filter((a) => a.id !== actionForDecision.id)
    : actionsHistory;

  const decisionIsExecutable =
    !!latestDecision &&
    latestDecision.status === "completed" &&
    latestDecision.policy_decision === "ALLOWED";

  return (
    <Card className="p-4">
      <SectionHeading eyebrow="Policy-authorized, sandbox-only" title="Sandbox action">
        <Badge variant="sandbox">SANDBOX</Badge>
      </SectionHeading>
      <p className="text-xs text-slate-400 mt-2">
        Only an ALLOWED, persisted Phase 6 decision may trigger a sandbox action. The executor is
        pure and deterministic -- it never contacts a real payment provider and never mutates
        financial event data. It relabels the decision&apos;s own preferred simulation under a
        scenario-specific action kind. Phase 8 outcome verification compares the expected
        simulation against the independently observed sandbox outcome.
      </p>

      <div className="mt-4">
        {!latestDecision && (
          <EmptyState>
            No decision has been evaluated for this investigation yet — run decision evaluation
            above before a sandbox action can be authorized.
          </EmptyState>
        )}

        {latestDecision && latestDecision.status !== "completed" && (
          <EmptyState>
            The latest decision has no eligible scenario to act on ({decisionSummaryLabel(latestDecision)}).
          </EmptyState>
        )}

        {latestDecision &&
          latestDecision.status === "completed" &&
          latestDecision.policy_decision !== "ALLOWED" && (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 flex-wrap">
                <Badge variant="neutral">POLICY</Badge>
                {latestDecision.policy_decision && (
                  <Badge variant={POLICY_COPY[latestDecision.policy_decision].variant}>
                    {POLICY_COPY[latestDecision.policy_decision].label}
                  </Badge>
                )}
              </div>
              <p className="text-sm text-slate-600">
                The preferred scenario ({decisionSummaryLabel(latestDecision)}) is not authorized
                for a sandbox action.
              </p>
              {latestDecision.policy_reasons.length > 0 && (
                <ul className="space-y-1">
                  {latestDecision.policy_reasons.map((reason) => (
                    <li key={reason} className="text-xs text-slate-500">
                      {reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

        {decisionIsExecutable && (
          <Button variant="secondary" onClick={onRun} disabled={running}>
            {running ? "Executing…" : actionForDecision ? "Re-run sandbox action" : "Execute in sandbox"}
          </Button>
        )}
      </div>

      {error && (
        <div className="mt-3">
          <ErrorText>{error}</ErrorText>
        </div>
      )}

      {decisionIsExecutable && (
        <div className="mt-4">
          {!actionForDecisionLoaded && <LoadingRow>Loading sandbox action…</LoadingRow>}
          {running && (
            <div className="mt-1">
              <LoadingRow>Executing…</LoadingRow>
            </div>
          )}
          {!running && actionForDecisionLoaded && actionForDecision && (
            <ActionResult action={actionForDecision} />
          )}
        </div>
      )}

      {history.length > 0 && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
            Sandbox action history
          </p>
          {!actionsLoaded && <LoadingRow>Loading sandbox action history…</LoadingRow>}
          <ul className="divide-y divide-slate-100">
            {history.map((action) => (
              <li key={action.id} className="py-2 flex items-center justify-between text-xs gap-2">
                <span className="text-slate-700 font-medium">
                  {action.scenario ? SCENARIO_LABELS[action.scenario] : "—"}
                </span>
                <Badge variant={ACTION_STATUS_COPY[action.status].variant}>
                  {ACTION_STATUS_COPY[action.status].label}
                </Badge>
                <span className="text-slate-400 font-mono">
                  {new Date(action.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function ActionResult({ action }: { action: Action }) {
  const statusCopy = ACTION_STATUS_COPY[action.status];

  if (action.status === "rejected") {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <Badge variant="sandbox">SANDBOX</Badge>
          <Badge variant={statusCopy.variant}>{statusCopy.label}</Badge>
        </div>
        <p className="text-sm text-slate-600">
          {action.rejection_reason ?? "The sandbox action was rejected."}
        </p>
      </div>
    );
  }

  const result = "action_kind" in action.sandbox_result ? action.sandbox_result : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant="sandbox">SANDBOX</Badge>
        <Badge variant={statusCopy.variant}>{statusCopy.label}</Badge>
        {result && <span className="text-sm font-semibold text-slate-900">{result.action_kind}</span>}
      </div>

      {result && (
        <div className="border border-slate-200 rounded-lg p-3 space-y-2">
          <div className="flex justify-between gap-4 text-sm">
            <span className="text-slate-500">Targeted events</span>
            <span className="text-slate-900 font-medium tabular-nums">
              {result.targeted_event_count}
            </span>
          </div>
          <div className="flex justify-between gap-4 text-sm">
            <span className="text-slate-500">Simulated outcome</span>
            <span className="text-slate-900 tabular-nums text-right">
              {result.simulated_outcome_by_currency.length > 0
                ? result.simulated_outcome_by_currency
                    .map((item) => `${item.amount} ${item.currency}`)
                    .join(", ")
                : "—"}
            </span>
          </div>
          <p className="text-xs text-slate-500">{result.note}</p>
        </div>
      )}

      <p className="text-xs font-medium text-teal-700">
        Sandbox-only — no real payment provider contacted.
      </p>
    </div>
  );
}

function OutcomeVerificationSection({
  latestAction,
  verificationForAction,
  verificationForActionLoaded,
  verificationsHistory,
  verificationsLoaded,
  running,
  error,
  onRun,
}: {
  latestAction: Action | null;
  verificationForAction: Verification | null;
  verificationForActionLoaded: boolean;
  verificationsHistory: Verification[];
  verificationsLoaded: boolean;
  running: boolean;
  error: string | null;
  onRun: () => void;
}) {
  // verificationsHistory already includes verificationForAction
  // (list_verifications is a superset of get_verification_for_action) --
  // avoid rendering it twice, mirroring the actionsHistory/actionForDecision
  // filter in SandboxActionSection above.
  const history = verificationForAction
    ? verificationsHistory.filter((v) => v.id !== verificationForAction.id)
    : verificationsHistory;

  const actionIsVerifiable = !!latestAction && latestAction.status === "executed";

  return (
    <Card className="p-4">
      <SectionHeading eyebrow="Deterministic, expected vs. observed" title="Outcome verification">
        <Badge variant="verification">VERIFICATION</Badge>
      </SectionHeading>
      <p className="text-xs text-slate-400 mt-2">
        Only an executed, persisted Phase 7 sandbox action may be verified. The verifier is pure
        and deterministic -- it never contacts a real payment provider, never recomputes the
        simulation, and never mutates the action or its sandbox result. It compares the action&apos;s
        own EXPECTED (Phase 5 projected) snapshot against its own OBSERVED (Phase 7 sandbox)
        snapshot, exact match only, per currency.
      </p>

      <div className="mt-4">
        {!latestAction && (
          <EmptyState>
            No sandbox action has been executed for this investigation yet — run a sandbox action
            above before its outcome can be verified.
          </EmptyState>
        )}

        {latestAction && latestAction.status === "rejected" && (
          <EmptyState>
            The latest sandbox action was rejected — a rejected action never produces an
            observable outcome, so there is nothing to verify.
          </EmptyState>
        )}

        {actionIsVerifiable && (
          <Button variant="secondary" onClick={onRun} disabled={running}>
            {running
              ? "Verifying…"
              : verificationForAction
                ? "Re-run verification"
                : "Verify outcome"}
          </Button>
        )}
      </div>

      {error && (
        <div className="mt-3">
          <ErrorText>{error}</ErrorText>
        </div>
      )}

      {actionIsVerifiable && (
        <div className="mt-4">
          {!verificationForActionLoaded && <LoadingRow>Loading outcome verification…</LoadingRow>}
          {running && (
            <div className="mt-1">
              <LoadingRow>Verifying…</LoadingRow>
            </div>
          )}
          {!running && verificationForActionLoaded && verificationForAction && (
            <VerificationResult verification={verificationForAction} />
          )}
        </div>
      )}

      {history.length > 0 && (
        <div className="mt-5 pt-4 border-t border-slate-100">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
            Verification history
          </p>
          {!verificationsLoaded && <LoadingRow>Loading verification history…</LoadingRow>}
          <ul className="divide-y divide-slate-100">
            {history.map((verification) => (
              <li
                key={verification.id}
                className="py-2 flex items-center justify-between text-xs gap-2"
              >
                <Badge variant={VERIFICATION_STATUS_COPY[verification.status].variant}>
                  {VERIFICATION_STATUS_COPY[verification.status].label}
                </Badge>
                <span className="text-slate-400 font-mono">
                  {new Date(verification.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function VerificationResult({ verification }: { verification: Verification }) {
  const statusCopy = VERIFICATION_STATUS_COPY[verification.status];
  const expected = verification.expected_snapshot;
  const observed = verification.observed_snapshot;
  const dimensions =
    "success_count" in verification.comparison.dimensions
      ? verification.comparison.dimensions
      : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant="verification">VERIFICATION</Badge>
        <Badge variant={statusCopy.variant}>{statusCopy.label}</Badge>
      </div>

      {verification.status === "INSUFFICIENT_OBSERVATION" && (
        <p className="text-sm text-slate-600">
          {!expected.available
            ? expected.reason
            : !observed.available
              ? observed.reason
              : "Insufficient observation to verify this outcome."}
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="border border-purple-200 rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <Badge variant="projected">PROJECTED</Badge>
            <span className="text-xs font-medium text-slate-500">Expected</span>
          </div>
          {expected.available ? (
            <dl className="space-y-1.5 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Eligible events</dt>
                <dd className="text-slate-900 font-medium tabular-nums">
                  {expected.eligible_event_count ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Projected success</dt>
                <dd className="text-slate-900 font-medium tabular-nums">
                  {expected.projected_success_count ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Projected failure</dt>
                <dd className="text-slate-900 font-medium tabular-nums">
                  {expected.projected_failure_count ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Estimated recovery</dt>
                <dd className="text-slate-900 tabular-nums text-right">
                  {formatCurrencyAmounts(expected.estimated_recovery_by_currency)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Projected exposure</dt>
                <dd className="text-slate-900 tabular-nums text-right">
                  {formatCurrencyAmounts(expected.projected_exposure_by_currency)}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-xs text-slate-500">{expected.reason}</p>
          )}
        </div>

        <div className="border border-teal-200 rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <Badge variant="sandbox">SANDBOX</Badge>
            <span className="text-xs font-medium text-slate-500">Observed</span>
          </div>
          {observed.available ? (
            <dl className="space-y-1.5 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Observed success</dt>
                <dd className="text-slate-900 font-medium tabular-nums">
                  {observed.observed_success_count ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Observed failure</dt>
                <dd className="text-slate-900 font-medium tabular-nums">
                  {observed.observed_failure_count ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500">Observed recovery</dt>
                <dd className="text-slate-900 tabular-nums text-right">
                  {formatCurrencyAmounts(observed.observed_recovery_by_currency)}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-xs text-slate-500">{observed.reason}</p>
          )}
        </div>
      </div>

      {dimensions && (
        <div className="border border-slate-200 rounded-lg p-3 space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Dimension comparison
          </p>
          <div className="flex justify-between gap-4 text-sm">
            <span className="text-slate-500">Success count</span>
            <span
              className={`font-medium tabular-nums ${dimensions.success_count.match ? "text-emerald-700" : "text-red-600"}`}
            >
              {dimensions.success_count.expected ?? "—"} vs {dimensions.success_count.observed ?? "—"}
              {dimensions.success_count.match ? " (match)" : " (mismatch)"}
            </span>
          </div>
          <div className="flex justify-between gap-4 text-sm">
            <span className="text-slate-500">Failure count</span>
            <span
              className={`font-medium tabular-nums ${dimensions.failure_count.match ? "text-emerald-700" : "text-red-600"}`}
            >
              {dimensions.failure_count.expected ?? "—"} vs {dimensions.failure_count.observed ?? "—"}
              {dimensions.failure_count.match ? " (match)" : " (mismatch)"}
            </span>
          </div>
          <div className="flex justify-between gap-4 text-sm">
            <span className="text-slate-500">Recovery by currency</span>
            <span
              className={`font-medium text-right ${dimensions.recovery_by_currency.match ? "text-emerald-700" : "text-red-600"}`}
            >
              {dimensions.recovery_by_currency.match ? "match" : "mismatch"}
            </span>
          </div>
          {(dimensions.recovery_by_currency.missing_currencies.length > 0 ||
            dimensions.recovery_by_currency.unexpected_currencies.length > 0 ||
            dimensions.recovery_by_currency.amount_mismatches.length > 0) && (
            <ul className="space-y-1 pt-1">
              {dimensions.recovery_by_currency.missing_currencies.map((currency) => (
                <li key={`missing-${currency}`} className="text-xs text-slate-500">
                  Missing observed amount for {currency}.
                </li>
              ))}
              {dimensions.recovery_by_currency.unexpected_currencies.map((currency) => (
                <li key={`unexpected-${currency}`} className="text-xs text-slate-500">
                  Unexpected observed amount for {currency}.
                </li>
              ))}
              {dimensions.recovery_by_currency.amount_mismatches.map((detail) => (
                <li key={`mismatch-${detail}`} className="text-xs text-slate-500">
                  {detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {verification.comparison.reasons.length > 0 && (
        <ul className="space-y-1">
          {verification.comparison.reasons.map((reason) => (
            <li key={reason} className="text-xs text-slate-500">
              {reason}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs font-medium text-fuchsia-700">
        Deterministic comparison only — no financial data mutated, no external systems contacted.
      </p>
    </div>
  );
}
