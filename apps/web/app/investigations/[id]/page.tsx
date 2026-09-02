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

const STATUS_COPY: Record<ReasoningStatus, { label: string; tone: "success" | "neutral" | "danger" }> = {
  completed: { label: "Reasoning complete", tone: "success" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "neutral" },
  unavailable: { label: "Reasoning unavailable", tone: "danger" },
  invalid_output: { label: "Reasoning output rejected", tone: "danger" },
  no_valid_hypotheses: { label: "No hypotheses proposed", tone: "neutral" },
};

export default function InvestigationDetailPage() {
  const params = useParams<{ id: string }>();
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reasoning, setReasoning] = useState<Reasoning | null>(null);
  const [reasoningLoaded, setReasoningLoaded] = useState(false);
  const [reasoningRunning, setReasoningRunning] = useState(false);
  const [reasoningError, setReasoningError] = useState<string | null>(null);

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
