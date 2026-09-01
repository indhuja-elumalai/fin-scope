"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

type FinancialEvent = {
  id: string;
  merchant_id: string;
  event_type: string;
  source: string;
  external_reference: string | null;
  amount: string | number | null;
  currency: string | null;
  status: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
  ingested_at: string;
};

export default function EventDetailPage() {
  const params = useParams<{ id: string }>();
  const [event, setEvent] = useState<FinancialEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/events/${params.id}`);
        if (response.status === 404) {
          throw new Error("Event not found.");
        }
        if (!response.ok) {
          throw new Error(`Failed to load event (${response.status})`);
        }
        const body = (await response.json()) as FinancialEvent;
        if (!cancelled) setEvent(body);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load event.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  const fields = event
    ? {
        ID: event.id,
        Merchant: event.merchant_id,
        "Event type": event.event_type,
        Source: event.source,
        "External reference": event.external_reference ?? "—",
        Amount: event.amount ? `${event.amount} ${event.currency ?? ""}` : "—",
        Status: event.status ?? "—",
        "Occurred at": new Date(event.occurred_at).toLocaleString(),
        "Ingested at": new Date(event.ingested_at).toLocaleString(),
      }
    : null;

  return (
    <main className="max-w-2xl mx-auto px-6 py-12">
      <Link href="/events" className="text-sm text-neutral-500 hover:underline">
        ← All events
      </Link>
      <h1 className="text-xl font-semibold mt-3">Event detail</h1>

      {loading && <p className="text-sm text-neutral-500 mt-4">Loading…</p>}
      {error && <p className="text-sm text-red-600 mt-4">{error}</p>}
      {event && fields && (
        <dl className="mt-6 border border-neutral-200 rounded-lg divide-y divide-neutral-200 text-sm">
          {Object.entries(fields).map(([label, value]) => (
            <div key={label} className="px-4 py-2.5 flex justify-between gap-4">
              <dt className="text-neutral-500">{label}</dt>
              <dd className="text-right break-all">{value}</dd>
            </div>
          ))}
          <div className="px-4 py-2.5">
            <dt className="text-neutral-500 mb-1">Payload</dt>
            <dd>
              <pre className="bg-neutral-50 rounded p-3 text-xs overflow-x-auto">
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            </dd>
          </div>
        </dl>
      )}
    </main>
  );
}
