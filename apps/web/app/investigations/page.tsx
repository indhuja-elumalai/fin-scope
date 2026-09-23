"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorText,
  Input,
  Label,
  LoadingRow,
  PageHeader,
  SectionHeading,
  Select,
  SuccessText,
} from "@/components/ui";

type Merchant = { id: string; name: string };

type Investigation = {
  id: string;
  merchant_id: string;
  incident_detected: boolean;
  evidence_event_count: number;
  dominant_signal_event_type: string | null;
  dominant_signal_share: string | null;
  created_at: string;
};

type InvestigationListResponse = {
  items: Investigation[];
  total: number;
};

export default function InvestigationsPage() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterMerchant, setFilterMerchant] = useState("");
  const [refreshIndex, setRefreshIndex] = useState(0);

  const [triggerMerchant, setTriggerMerchant] = useState("");
  const [triggerAsOf, setTriggerAsOf] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // Populates the merchant dropdown once on mount, same pattern as
  // app/events/page.tsx -- independent of the investigation list below.
  useEffect(() => {
    let ignore = false;

    fetch("/api/merchants")
      .then((response) => (response.ok ? (response.json() as Promise<Merchant[]>) : null))
      .then((body) => {
        if (!ignore && body) {
          setMerchants(body);
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  // Loads the investigation list for the current filter. `loading` is set
  // synchronously by the event handler that changes a dependency (filter
  // change or post-trigger refresh), never inside this Effect itself.
  useEffect(() => {
    let ignore = false;
    const params = new URLSearchParams();
    if (filterMerchant) params.set("merchant_id", filterMerchant);

    fetch(`/api/investigations?${params.toString()}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load investigations (${response.status})`);
        }
        return response.json() as Promise<InvestigationListResponse>;
      })
      .then((body) => {
        if (!ignore) {
          setInvestigations(body.items);
          setTotal(body.total);
          setError(null);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load investigations.");
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [filterMerchant, refreshIndex]);

  const merchantNames = new Map(merchants.map((m) => [m.id, m.name]));

  function handleFilterMerchantChange(value: string) {
    setLoading(true);
    setFilterMerchant(value);
  }

  async function handleTrigger(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const response = await fetch("/api/investigations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          merchant_id: triggerMerchant,
          as_of: triggerAsOf ? new Date(triggerAsOf).toISOString() : null,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
          : body.detail;
        throw new Error(typeof detail === "string" ? detail : "Failed to run investigation.");
      }
      setSubmitSuccess(
        body.incident_detected
          ? `Incident detected — ${body.evidence_event_count} concerning events, dominant signal: ${body.dominant_signal_event_type}.`
          : `No incident detected (${body.evidence_event_count} concerning events in window).`
      );
      setLoading(true);
      setRefreshIndex((i) => i + 1);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to run investigation.");
    } finally {
      setSubmitting(false);
    }
  }

  const incidentCount = investigations.filter((inv) => inv.incident_detected).length;

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-10">
      <PageHeader
        eyebrow="SYS://fin-scope/investigations"
        title="Incident investigations"
        description="Run a deterministic FIND → dominant-signal → impact analysis over a merchant's recent financial events, then reason about plausible, evidence-grounded explanations."
      />

      <div className="grid lg:grid-cols-[340px_1fr] gap-6 mt-8 items-start">
        <Card className="p-5 lg:sticky lg:top-20">
          <form onSubmit={handleTrigger} className="space-y-5">
            <SectionHeading eyebrow="Operator input" title="Launch run" />
            <div>
              <Label htmlFor="investigation-merchant">Target merchant</Label>
              <Select
                id="investigation-merchant"
                required
                value={triggerMerchant}
                onChange={(e) => setTriggerMerchant(e.target.value)}
              >
                <option value="">Select a merchant…</option>
                {merchants.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
              {merchants.length === 0 && (
                <p className="text-xs text-slate-400 mt-1.5">
                  No merchants yet —{" "}
                  <Link href="/merchants" className="text-blue-600 hover:underline">
                    create one first
                  </Link>
                  .
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="investigation-as-of">As of · optional, defaults to now</Label>
              <Input
                id="investigation-as-of"
                type="datetime-local"
                value={triggerAsOf}
                onChange={(e) => setTriggerAsOf(e.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting || !triggerMerchant}>
              {submitting ? "Investigating…" : "▶ Run investigation"}
            </Button>
            {submitError && <ErrorText>{submitError}</ErrorText>}
            {submitSuccess && <SuccessText>{submitSuccess}</SuccessText>}
            <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-400 leading-relaxed pt-3 border-t border-dashed border-slate-200">
              Deterministic FIND · no AI call · no side effects
            </p>
          </form>
        </Card>

        <div className="min-w-0">
          <div className="flex gap-4 items-end justify-between mb-4 flex-wrap">
            <div>
              <Label htmlFor="filter-merchant">Filter by merchant</Label>
              <Select
                id="filter-merchant"
                value={filterMerchant}
                onChange={(e) => handleFilterMerchantChange(e.target.value)}
                className="min-w-[14rem]"
              >
                <option value="">All merchants</option>
                {merchants.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex items-center gap-4 pb-2 font-mono text-[10.5px] uppercase tracking-[0.12em] tabular-nums">
              <span className="text-slate-500">
                <span className="text-slate-900">{total}</span> total
              </span>
              {!loading && investigations.length > 0 && (
                <span className="text-red-600">
                  <span className="text-red-500">{incidentCount}</span> incidents on page
                </span>
              )}
            </div>
          </div>

          {loading && (
            <Card className="p-5">
              <LoadingRow>Loading investigations</LoadingRow>
            </Card>
          )}
          {error && <ErrorText>{error}</ErrorText>}
          {!loading && !error && investigations.length === 0 && (
            <EmptyState>No investigations match this filter.</EmptyState>
          )}
          {!loading && investigations.length > 0 && (
            <Card>
              <ul className="divide-y divide-slate-100">
                {investigations.map((inv, i) => (
                  <li key={inv.id}>
                    <Link
                      href={`/investigations/${inv.id}`}
                      className="group relative px-4 py-4 flex justify-between items-center gap-4 hover:bg-sky-50 transition-colors"
                    >
                      <span
                        className={`absolute left-0 top-2 bottom-2 w-[2px] ${
                          inv.incident_detected
                            ? "bg-red-400 shadow-[0_0_10px_var(--danger)]"
                            : "bg-slate-300"
                        }`}
                        aria-hidden="true"
                      />
                      <div className="flex items-center gap-4 min-w-0">
                        <span className="font-mono text-[10px] text-slate-300 tabular-nums w-5 shrink-0">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2.5 flex-wrap">
                            <Badge variant={inv.incident_detected ? "danger" : "neutral"}>
                              {inv.incident_detected ? "Incident" : "No incident"}
                            </Badge>
                            <span className="font-mono text-[11px] text-slate-500 tabular-nums">
                              {inv.evidence_event_count} event
                              {inv.evidence_event_count === 1 ? "" : "s"}
                            </span>
                            {merchantNames.get(inv.merchant_id) && (
                              <span className="text-sm text-slate-900 truncate">
                                {merchantNames.get(inv.merchant_id)}
                              </span>
                            )}
                          </div>
                          <div className="font-mono text-[11px] text-slate-400 mt-1 truncate">
                            {new Date(inv.created_at).toLocaleString()} · {inv.id.slice(0, 8)}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <div className="text-right">
                          <div className="font-mono text-xs text-slate-700">
                            {inv.dominant_signal_event_type ?? "—"}
                          </div>
                          {inv.dominant_signal_share && (
                            <div className="mt-1.5 w-24 h-[3px] bg-slate-200 ml-auto">
                              <div
                                className={`h-full ${
                                  inv.incident_detected ? "bg-red-400" : "bg-[var(--accent)]"
                                }`}
                                style={{
                                  width: `${Math.min(100, Number(inv.dominant_signal_share) * 100)}%`,
                                }}
                              />
                            </div>
                          )}
                        </div>
                        <span className="text-[var(--accent)] opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all">
                          →
                        </span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}
