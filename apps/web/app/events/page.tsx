"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import {
  Button,
  Card,
  EmptyState,
  ErrorText,
  Input,
  Label,
  Led,
  LoadingRow,
  PageHeader,
  SectionHeading,
  Select,
  SuccessText,
  Telemetry,
} from "@/components/ui";

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

const CONCERNING_TYPES = new Set(["payment_failed", "settlement_delayed", "gateway_degraded"]);

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
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-10">
      <PageHeader
        eyebrow="SYS://fin-scope/events"
        title="Financial events"
        description="Ingest and inspect financial events through the real API and database. Re-sending an external reference is an idempotent replay."
      />

      <div className="grid lg:grid-cols-[380px_1fr] gap-6 mt-8 items-start">
        <Card className="p-5 lg:sticky lg:top-20">
          <form onSubmit={handleCreate} className="space-y-4">
            <SectionHeading eyebrow="Ingest" title="Push event" />
            <div>
              <Label htmlFor="event-merchant">Merchant</Label>
              <Select
                id="event-merchant"
                required
                value={form.merchant_id}
                onChange={(e) => setForm({ ...form, merchant_id: e.target.value })}
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
              <Label htmlFor="event-type">Event type</Label>
              <Select
                id="event-type"
                value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value })}
              >
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="event-source">Source</Label>
                <Input
                  id="event-source"
                  value={form.source}
                  onChange={(e) => setForm({ ...form, source: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="event-status">Status</Label>
                <Input
                  id="event-status"
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="event-amount">Amount</Label>
                <Input
                  id="event-amount"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="event-currency">Currency</Label>
                <Input
                  id="event-currency"
                  value={form.currency}
                  maxLength={3}
                  onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                />
              </div>
            </div>
            <div>
              <Label htmlFor="event-external-reference">External reference · optional</Label>
              <Input
                id="event-external-reference"
                value={form.external_reference}
                onChange={(e) => setForm({ ...form, external_reference: e.target.value })}
                placeholder="Leave set to test idempotent re-send"
              />
            </div>
            <div>
              <Label htmlFor="event-occurred-at">Occurred at · defaults to now</Label>
              <Input
                id="event-occurred-at"
                type="datetime-local"
                value={form.occurred_at}
                onChange={(e) => setForm({ ...form, occurred_at: e.target.value })}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting || !form.merchant_id}>
              {submitting ? "Ingesting…" : "↥ Ingest event"}
            </Button>
            {submitError && <ErrorText>{submitError}</ErrorText>}
            {submitSuccess && <SuccessText>{submitSuccess}</SuccessText>}
          </form>
        </Card>

        <div className="min-w-0">
          <div className="flex gap-3 items-end mb-4 flex-wrap">
            <div>
              <Label htmlFor="filter-merchant">Filter by merchant</Label>
              <Select
                id="filter-merchant"
                value={filterMerchant}
                onChange={(e) => handleFilterMerchantChange(e.target.value)}
                className="min-w-[12rem]"
              >
                <option value="">All merchants</option>
                {merchants.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="filter-type">Filter by type</Label>
              <Select
                id="filter-type"
                value={filterType}
                onChange={(e) => handleFilterTypeChange(e.target.value)}
                className="min-w-[10rem]"
              >
                <option value="">All types</option>
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </div>
            <span className="ml-auto pb-3 font-mono text-[10.5px] uppercase tracking-[0.12em] text-slate-500 tabular-nums">
              <span className="text-slate-900">{total}</span> total
            </span>
          </div>

          {loading && (
            <Card className="p-5">
              <LoadingRow>Streaming events</LoadingRow>
            </Card>
          )}
          {error && <ErrorText>{error}</ErrorText>}
          {!loading && !error && events.length === 0 && (
            <EmptyState>No events match these filters.</EmptyState>
          )}
          {!loading && events.length > 0 && (
            <Card>
              <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between">
                <Telemetry slashes>Event stream</Telemetry>
                <span className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.12em] text-slate-400">
                  <span className="flex items-center gap-1.5">
                    <Led tone="warn" /> Concerning
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Led tone="ok" /> Nominal
                  </span>
                </span>
              </div>
              <ul className="divide-y divide-slate-100">
                {events.map((ev) => {
                  const concerning = CONCERNING_TYPES.has(ev.event_type);
                  return (
                    <li key={ev.id}>
                      <Link
                        href={`/events/${ev.id}`}
                        className="group px-4 py-3.5 flex justify-between items-center gap-4 hover:bg-sky-50 transition-colors"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <Led tone={concerning ? "warn" : "ok"} />
                          <div className="min-w-0">
                            <div
                              className={`font-mono text-[13px] truncate ${
                                concerning ? "text-amber-700" : "text-slate-900"
                              }`}
                            >
                              {ev.event_type}
                            </div>
                            <div className="font-mono text-[11px] text-slate-400 mt-0.5">
                              {ev.source} · {new Date(ev.occurred_at).toLocaleString()}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="font-mono text-[13px] tabular-nums text-slate-900">
                            {ev.amount ? (
                              <>
                                {ev.amount}{" "}
                                <span className="text-slate-400 text-[11px]">
                                  {ev.currency ?? ""}
                                </span>
                              </>
                            ) : (
                              <span className="text-slate-300">—</span>
                            )}
                          </span>
                          <span className="text-[var(--accent)] opacity-0 group-hover:opacity-100 transition-opacity">
                            →
                          </span>
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </main>
  );
}
