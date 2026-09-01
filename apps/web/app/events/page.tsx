"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

// Mirrors app.domain.events.KNOWN_EVENT_TYPES on the backend. Phase 2 keeps
// this a plain hardcoded list on both sides rather than fetching a
// type catalog endpoint that does not exist yet.
const EVENT_TYPES = [
  "payment_failed",
  "payment_succeeded",
  "refund_issued",
  "settlement_delayed",
  "gateway_degraded",
] as const;

type Merchant = { id: string; name: string };

type FinancialEvent = {
  id: string;
  merchant_id: string;
  event_type: string;
  source: string;
  amount: string | number | null;
  currency: string | null;
  occurred_at: string;
};

type EventListResponse = {
  items: FinancialEvent[];
  total: number;
};

type FormState = {
  merchant_id: string;
  event_type: string;
  source: string;
  external_reference: string;
  amount: string;
  currency: string;
  status: string;
  occurred_at: string;
};

const EMPTY_FORM: FormState = {
  merchant_id: "",
  event_type: EVENT_TYPES[0],
  source: "manual",
  external_reference: "",
  amount: "",
  currency: "",
  status: "",
  occurred_at: "",
};

export default function EventsPage() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [events, setEvents] = useState<FinancialEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterMerchant, setFilterMerchant] = useState("");
  const [filterType, setFilterType] = useState("");
  const [refreshIndex, setRefreshIndex] = useState(0);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // Populates the merchant dropdown once on mount. No loading indicator is
  // shown for this (matches the original design) -- it is purely a
  // synchronization with the backend, independent of the event list below.
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

  // Loads the event list for the current filters. This Effect only
  // synchronizes with the backend and reports the outcome -- it never
  // decides on its own that loading has (re)started. Filter changes and
  // the post-ingest refresh both set `loading` from the event handler that
  // caused them, before changing the dependencies below.
  useEffect(() => {
    let ignore = false;
    const params = new URLSearchParams();
    if (filterMerchant) params.set("merchant_id", filterMerchant);
    if (filterType) params.set("event_type", filterType);

    fetch(`/api/events?${params.toString()}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load events (${response.status})`);
        }
        return response.json() as Promise<EventListResponse>;
      })
      .then((body) => {
        if (!ignore) {
          setEvents(body.items);
          setTotal(body.total);
          setError(null);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load events.");
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
  }, [filterMerchant, filterType, refreshIndex]);

  function handleFilterMerchantChange(value: string) {
    setLoading(true);
    setFilterMerchant(value);
  }

  function handleFilterTypeChange(value: string) {
    setLoading(true);
    setFilterType(value);
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const response = await fetch("/api/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          merchant_id: form.merchant_id,
          event_type: form.event_type,
          source: form.source,
          external_reference: form.external_reference || null,
          amount: form.amount || null,
          currency: form.currency || null,
          status: form.status || null,
          occurred_at: form.occurred_at
            ? new Date(form.occurred_at).toISOString()
            : new Date().toISOString(),
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
          : body.detail;
        throw new Error(typeof detail === "string" ? detail : "Failed to ingest event.");
      }
      setSubmitSuccess(
        response.status === 200
          ? `Event already existed (idempotent replay) — id ${body.id}.`
          : `Ingested event ${body.id}.`
      );
      setForm({ ...EMPTY_FORM, merchant_id: form.merchant_id });
      setLoading(true);
      setRefreshIndex((i) => i + 1);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to ingest event.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-xl font-semibold">Financial events</h1>
      <p className="text-sm text-neutral-500 mt-1">
        Ingest and inspect financial events through the real API and database.
      </p>

      <form
        onSubmit={handleCreate}
        className="mt-8 border border-neutral-200 rounded-lg p-5 space-y-3"
      >
        <h2 className="font-medium text-sm">Ingest event</h2>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="event-merchant">
              Merchant
            </label>
            <select
              id="event-merchant"
              required
              value={form.merchant_id}
              onChange={(e) => setForm({ ...form, merchant_id: e.target.value })}
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
            <label className="block text-sm text-neutral-600" htmlFor="event-type">
              Event type
            </label>
            <select
              id="event-type"
              value={form.event_type}
              onChange={(e) => setForm({ ...form, event_type: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            >
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="event-source">
              Source
            </label>
            <input
              id="event-source"
              value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label
              className="block text-sm text-neutral-600"
              htmlFor="event-external-reference"
            >
              External reference (optional)
            </label>
            <input
              id="event-external-reference"
              value={form.external_reference}
              onChange={(e) => setForm({ ...form, external_reference: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
              placeholder="Leave set to test idempotent re-send"
            />
          </div>
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="event-amount">
              Amount (optional)
            </label>
            <input
              id="event-amount"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="event-currency">
              Currency (optional)
            </label>
            <input
              id="event-currency"
              value={form.currency}
              maxLength={3}
              onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-neutral-600" htmlFor="event-status">
              Status (optional)
            </label>
            <input
              id="event-status"
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label
              className="block text-sm text-neutral-600"
              htmlFor="event-occurred-at"
            >
              Occurred at (optional, defaults to now)
            </label>
            <input
              id="event-occurred-at"
              type="datetime-local"
              value={form.occurred_at}
              onChange={(e) => setForm({ ...form, occurred_at: e.target.value })}
              className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={submitting || !form.merchant_id}
          className="bg-neutral-900 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50"
        >
          {submitting ? "Ingesting…" : "Ingest event"}
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
          <div>
            <label className="block text-xs text-neutral-500" htmlFor="filter-type">
              Filter by type
            </label>
            <select
              id="filter-type"
              value={filterType}
              onChange={(e) => handleFilterTypeChange(e.target.value)}
              className="mt-1 border border-neutral-300 rounded px-2 py-1 text-sm"
            >
              <option value="">All types</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <span className="text-xs text-neutral-400">{total} total</span>
        </div>

        {loading && <p className="text-sm text-neutral-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && events.length === 0 && (
          <p className="text-sm text-neutral-500">No events match these filters.</p>
        )}
        {!loading && events.length > 0 && (
          <ul className="divide-y divide-neutral-200 border border-neutral-200 rounded-lg">
            {events.map((ev) => (
              <li key={ev.id} className="px-4 py-3 text-sm flex justify-between items-center">
                <div>
                  <Link href={`/events/${ev.id}`} className="font-medium hover:underline">
                    {ev.event_type}
                  </Link>
                  <div className="text-neutral-400 text-xs">
                    {ev.source} · {new Date(ev.occurred_at).toLocaleString()}
                  </div>
                </div>
                <span className="text-neutral-500 text-xs">
                  {ev.amount ? `${ev.amount} ${ev.currency ?? ""}` : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
