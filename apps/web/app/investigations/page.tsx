"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

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
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-xl font-semibold">Incident investigations</h1>
      <p className="text-sm text-neutral-500 mt-1">
        Run a deterministic FIND → dominant-signal → impact analysis over a
        merchant&apos;s recent financial events. The dominant signal is a
        frequency heuristic, not a causal finding.
      </p>

      <form
        onSubmit={handleTrigger}
        className="mt-8 border border-neutral-200 rounded-lg p-5 space-y-3"
      >
        <h2 className="font-medium text-sm">Run investigation</h2>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="investigation-merchant">
              Merchant
            </label>
            <select
              id="investigation-merchant"
              required
              value={triggerMerchant}
              onChange={(e) => setTriggerMerchant(e.target.value)}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            >
              <option value="">Select a merchant…</option>
              {merchants.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            {merchants.length === 0 && (
              <p className="text-xs text-neutral-400 mt-1">
                No merchants yet —{" "}
                <Link href="/merchants" className="underline">
                  create one first
                </Link>
                .
              </p>
            )}
          </div>
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="investigation-as-of">
              As of (optional, defaults to now)
            </label>
            <input
              id="investigation-as-of"
              type="datetime-local"
              value={triggerAsOf}
              onChange={(e) => setTriggerAsOf(e.target.value)}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={submitting || !triggerMerchant}
          className="bg-neutral-900 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50"
        >
          {submitting ? "Investigating…" : "Run investigation"}
        </button>
        {submitError && <p className="text-sm text-red-600">{submitError}</p>}
        {submitSuccess && <p className="text-sm text-green-700">{submitSuccess}</p>}
      </form>

      <div className="mt-8">
        <div className="flex gap-3 items-end mb-3">
          <div>
            <label className="block text-xs text-neutral-500" htmlFor="filter-merchant">
              Filter by merchant
            </label>
            <select
              id="filter-merchant"
              value={filterMerchant}
              onChange={(e) => handleFilterMerchantChange(e.target.value)}
              className="mt-1 border border-neutral-300 rounded px-2 py-1 text-sm"
            >
              <option value="">All merchants</option>
              {merchants.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
          <span className="text-xs text-neutral-400">{total} total</span>
        </div>

        {loading && <p className="text-sm text-neutral-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && investigations.length === 0 && (
          <p className="text-sm text-neutral-500">No investigations match this filter.</p>
        )}
        {!loading && investigations.length > 0 && (
          <ul className="divide-y divide-neutral-200 border border-neutral-200 rounded-lg">
            {investigations.map((inv) => (
              <li key={inv.id} className="px-4 py-3 text-sm flex justify-between items-center">
                <div>
                  <Link href={`/investigations/${inv.id}`} className="font-medium hover:underline">
                    {inv.incident_detected ? "Incident detected" : "No incident"}
                  </Link>
                  <div className="text-neutral-400 text-xs">
                    {inv.evidence_event_count} events · {new Date(inv.created_at).toLocaleString()}
                  </div>
                </div>
                <span className="text-neutral-500 text-xs">
                  {inv.dominant_signal_event_type ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
