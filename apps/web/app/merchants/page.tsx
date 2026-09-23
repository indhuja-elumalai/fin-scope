"use client";

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
  SuccessText,
  Telemetry,
} from "@/components/ui";

type Merchant = {
  id: string;
  name: string;
  segment: string | null;
  created_at: string;
};

export default function MerchantsPage() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);

  const [name, setName] = useState("");
  const [segment, setSegment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // This Effect only synchronizes with the backend: fetch, then report
  // success/failure/done. It never decides on its own that a reload is
  // needed -- `refreshIndex` is the signal for that, bumped by the event
  // handler below (which also sets `loading` itself, since that's a
  // direct consequence of the user's action, not something the Effect
  // should infer).
  useEffect(() => {
    let ignore = false;

    fetch("/api/merchants")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load merchants (${response.status})`);
        }
        return response.json() as Promise<Merchant[]>;
      })
      .then((body) => {
        if (!ignore) {
          setMerchants(body);
          setError(null);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setError(err instanceof Error ? err.message : "Failed to load merchants.");
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
  }, [refreshIndex]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const response = await fetch("/api/merchants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, segment: segment || null }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to create merchant."
        );
      }
      setSubmitSuccess(`Created merchant "${body.name}".`);
      setName("");
      setSegment("");
      setLoading(true);
      setRefreshIndex((i) => i + 1);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create merchant.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-10">
      <PageHeader
        eyebrow="SYS://fin-scope/merchants"
        title="Merchants"
        description="Merchants are the tenant boundary every financial event attaches to."
      />

      <div className="grid lg:grid-cols-[340px_1fr] gap-6 mt-8 items-start">
        <Card className="p-5 lg:sticky lg:top-20">
          <form onSubmit={handleCreate} className="space-y-5">
            <SectionHeading eyebrow="Register" title="New merchant" />
            <div>
              <Label htmlFor="merchant-name">Name</Label>
              <Input
                id="merchant-name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="merchant-segment">Segment · optional</Label>
              <Input
                id="merchant-segment"
                value={segment}
                onChange={(e) => setSegment(e.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting || !name}>
              {submitting ? "Creating…" : "+ Create merchant"}
            </Button>
            {submitError && <ErrorText>{submitError}</ErrorText>}
            {submitSuccess && <SuccessText>{submitSuccess}</SuccessText>}
          </form>
        </Card>

        <div className="min-w-0">
          <div className="flex items-end justify-between mb-4">
            <Telemetry slashes>Registry</Telemetry>
            {!loading && (
              <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-slate-500 tabular-nums">
                <span className="text-slate-900">{merchants.length}</span> registered
              </span>
            )}
          </div>
          {loading && (
            <Card className="p-5">
              <LoadingRow>Loading merchants</LoadingRow>
            </Card>
          )}
          {error && <ErrorText>{error}</ErrorText>}
          {!loading && !error && merchants.length === 0 && (
            <EmptyState>No merchants yet.</EmptyState>
          )}
          {!loading && merchants.length > 0 && (
            <div className="grid sm:grid-cols-2 gap-4">
              {merchants.map((m, i) => (
                <Card key={m.id} className="p-4">
                  <div className="flex items-start gap-3">
                    <span className="chamfer-sm shrink-0 w-10 h-10 flex items-center justify-center border border-sky-200 bg-sky-50 font-[family-name:var(--font-display)] text-sm font-bold text-[var(--accent)]">
                      {m.name.slice(0, 2).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-900 font-medium truncate">{m.name}</span>
                        <span className="font-mono text-[10px] text-slate-300 tabular-nums">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        {m.segment ? (
                          <Badge variant="decision">{m.segment}</Badge>
                        ) : (
                          <span className="telemetry text-slate-300">No segment</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 pt-3 border-t border-dashed border-slate-200 flex items-center justify-between gap-3 font-mono text-[10.5px] text-slate-400">
                    <span className="truncate" title={m.id}>
                      ID {m.id}
                    </span>
                    <span className="shrink-0">
                      {new Date(m.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
