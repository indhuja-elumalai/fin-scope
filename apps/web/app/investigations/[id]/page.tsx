"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

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

export default function InvestigationDetailPage() {
  const params = useParams<{ id: string }>();
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <main className="max-w-2xl mx-auto px-6 py-12">
      <Link href="/investigations" className="text-sm text-neutral-500 hover:underline">
        ← All investigations
      </Link>
      <h1 className="text-xl font-semibold mt-3">Investigation detail</h1>

      {loading && <p className="text-sm text-neutral-500 mt-4">Loading…</p>}
      {error && <p className="text-sm text-red-600 mt-4">{error}</p>}

      {investigation && (
        <div className="mt-6 space-y-6">
          <dl className="border border-neutral-200 rounded-lg divide-y divide-neutral-200 text-sm">
            <div className="px-4 py-2.5 flex justify-between gap-4">
              <dt className="text-neutral-500">Merchant</dt>
              <dd className="text-right break-all">{investigation.merchant_id}</dd>
            </div>
            <div className="px-4 py-2.5 flex justify-between gap-4">
              <dt className="text-neutral-500">Window</dt>
              <dd className="text-right">
                {new Date(investigation.window_start).toLocaleString()} –{" "}
                {new Date(investigation.window_end).toLocaleString()}
              </dd>
            </div>
            <div className="px-4 py-2.5 flex justify-between gap-4">
              <dt className="text-neutral-500">Incident detected (FIND)</dt>
              <dd className="text-right">{investigation.incident_detected ? "Yes" : "No"}</dd>
            </div>
            <div className="px-4 py-2.5 flex justify-between gap-4">
              <dt className="text-neutral-500">Evidence event count</dt>
              <dd className="text-right">{investigation.evidence_event_count}</dd>
            </div>
          </dl>

          <section className="border border-neutral-200 rounded-lg p-4">
            <h2 className="font-medium text-sm">
              Dominant signal <span className="text-neutral-400 font-normal">(heuristic, not a cause)</span>
            </h2>
            <p className="text-sm text-neutral-600 mt-2">
              {investigation.dominant_signal_event_type
                ? `"${investigation.dominant_signal_event_type}" recurred most often — ${(
                    Number(investigation.dominant_signal_share) * 100
                  ).toFixed(0)}% of the evidence in this window.`
                : "No dominant signal — insufficient evidence in this window."}
            </p>
          </section>

          <section className="border border-neutral-200 rounded-lg p-4">
            <h2 className="font-medium text-sm">Impact (currency-safe)</h2>
            {investigation.impact_breakdown.length === 0 ? (
              <p className="text-sm text-neutral-500 mt-2">No amounts recorded for this evidence.</p>
            ) : (
              <ul className="mt-2 space-y-1 text-sm">
                {investigation.impact_breakdown.map((item) => (
                  <li key={item.currency}>
                    {item.total_amount} {item.currency} across {item.event_count} event
                    {item.event_count === 1 ? "" : "s"}
                  </li>
                ))}
              </ul>
            )}
            {investigation.impact_amount_unknown_count > 0 && (
              <p className="text-xs text-neutral-400 mt-2">
                {investigation.impact_amount_unknown_count} evidence event
                {investigation.impact_amount_unknown_count === 1 ? "" : "s"} had no recorded amount
                and were excluded from the totals above.
              </p>
            )}
          </section>

          <section className="border border-neutral-200 rounded-lg p-4">
            <h2 className="font-medium text-sm">Evidence timeline</h2>
            {investigation.evidence.length === 0 ? (
              <p className="text-sm text-neutral-500 mt-2">No evidence events in this window.</p>
            ) : (
              <ul className="mt-2 divide-y divide-neutral-100 text-sm">
                {investigation.evidence.map((item) => (
                  <li key={item.event_id} className="py-2 flex justify-between items-center">
                    <div>
                      <Link href={`/events/${item.event_id}`} className="hover:underline">
                        {item.event_type}
                      </Link>
                      <div className="text-neutral-400 text-xs">
                        {item.source} · {new Date(item.occurred_at).toLocaleString()}
                      </div>
                    </div>
                    <span className="text-neutral-500 text-xs">
                      {item.amount ? `${item.amount} ${item.currency ?? ""}` : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
