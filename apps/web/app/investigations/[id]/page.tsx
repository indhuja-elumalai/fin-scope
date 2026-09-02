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
