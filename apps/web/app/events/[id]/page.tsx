"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Card,
  ErrorText,
  KeyValueRow,
  LoadingRow,
  PageHeader,
  SectionHeading,
} from "@/components/ui";

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
    <main className="max-w-4xl mx-auto px-4 sm:px-6 py-10">
      <Link
        href="/events"
        className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-slate-500 hover:text-[var(--accent)] transition-colors"
      >
        ← All events
      </Link>

      <div className="mt-4">
        <PageHeader
          eyebrow="SYS://fin-scope/events/detail"
          title={event ? event.event_type : "Event detail"}
        >
          {event && (
            <span className="font-mono text-[11px] text-slate-400">{event.id}</span>
          )}
        </PageHeader>
      </div>

      {loading && <div className="mt-6"><LoadingRow>Loading event</LoadingRow></div>}
      {error && <div className="mt-6"><ErrorText>{error}</ErrorText></div>}
      {event && fields && (
        <div className="mt-8 grid md:grid-cols-2 gap-6 items-start">
          <Card>
            <div className="px-4 pt-4">
              <SectionHeading eyebrow="Record" title="Fields" />
            </div>
            <dl className="divide-y divide-slate-100">
              {Object.entries(fields).map(([label, value]) => (
                <KeyValueRow key={label} label={label} value={value} />
              ))}
            </dl>
          </Card>
          <Card className="p-4">
            <SectionHeading eyebrow="Raw" title="Payload" />
            <pre className="mt-3 bg-[#070c12] border border-slate-200 p-4 font-mono text-xs leading-relaxed overflow-x-auto text-emerald-700">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </Card>
        </div>
      )}
    </main>
  );
}
