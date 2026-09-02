"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Card, ErrorText, KeyValueRow, LoadingRow } from "@/components/ui";

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
    <main className="max-w-2xl mx-auto px-6 py-10">
      <Link href="/events" className="text-sm text-slate-500 hover:text-slate-900 transition-colors">
        ← All events
      </Link>
      <h1 className="text-xl font-semibold text-slate-900 mt-3">Event detail</h1>

      {loading && <div className="mt-4"><LoadingRow>Loading event…</LoadingRow></div>}
      {error && <div className="mt-4"><ErrorText>{error}</ErrorText></div>}
      {event && fields && (
        <div className="mt-6 space-y-6">
          <Card>
            <dl className="divide-y divide-slate-100">
              {Object.entries(fields).map(([label, value]) => (
                <KeyValueRow key={label} label={label} value={value} />
              ))}
            </dl>
          </Card>
          <Card className="p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-2">
              Payload
            </p>
            <pre className="bg-slate-50 border border-slate-100 rounded-lg p-3 text-xs overflow-x-auto text-slate-700">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </Card>
        </div>
      )}
    </main>
  );
}
