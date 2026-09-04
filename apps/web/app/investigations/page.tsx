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

  return (
    <main className="max-w-4xl mx-auto px-6 py-10">
      <PageHeader
        eyebrow="Workflow"
        title="Incident investigations"
        description="Run a deterministic FIND → dominant-signal → impact analysis over a merchant's recent financial events, then reason about plausible, evidence-grounded explanations."
      />

      <Card className="mt-8 p-5">
        <form onSubmit={handleTrigger} className="space-y-4">
          <h2 className="font-medium text-sm text-slate-900">Run investigation</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <Label htmlFor="investigation-merchant">Merchant</Label>
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
              <Label htmlFor="investigation-as-of">As of (optional, defaults to now)</Label>
              <Input
                id="investigation-as-of"
                type="datetime-local"
                value={triggerAsOf}
                onChange={(e) => setTriggerAsOf(e.target.value)}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={submitting || !triggerMerchant}>
              {submitting ? "Investigating…" : "Run investigation"}
            </Button>
          </div>
          {submitError && <ErrorText>{submitError}</ErrorText>}
          {submitSuccess && <SuccessText>{submitSuccess}</SuccessText>}
        </form>
      </Card>

      <div className="mt-8">
        <div className="flex gap-4 items-end justify-between mb-3 flex-wrap">
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
          <span className="text-xs text-slate-400 pb-2 tabular-nums">{total} total</span>
        </div>

        {loading && (
          <Card className="p-5">
            <LoadingRow>Loading investigations…</LoadingRow>
          </Card>
        )}
        {error && <ErrorText>{error}</ErrorText>}
        {!loading && !error && investigations.length === 0 && (
          <EmptyState>No investigations match this filter.</EmptyState>
        )}
        {!loading && investigations.length > 0 && (
          <Card>
            <ul className="divide-y divide-slate-100">
              {investigations.map((inv) => (
                <li key={inv.id}>
                  <Link
                    href={`/investigations/${inv.id}`}
                    className="px-4 py-3.5 flex justify-between items-center gap-4 hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`w-1.5 h-8 rounded-full shrink-0 ${
                          inv.incident_detected ? "bg-red-400" : "bg-slate-200"
                        }`}
                        aria-hidden="true"
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge variant={inv.incident_detected ? "danger" : "neutral"}>
                            {inv.incident_detected ? "Incident" : "No incident"}
                          </Badge>
                          <span className="text-xs text-slate-400 tabular-nums">
                            {inv.evidence_event_count} event
                            {inv.evidence_event_count === 1 ? "" : "s"}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5 truncate">
                          {new Date(inv.created_at).toLocaleString()}
                        </div>
                      </div>
                    </div>
                    <span className="text-slate-500 text-xs shrink-0 font-medium">
                      {inv.dominant_signal_event_type ?? "—"}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </main>
  );
}
