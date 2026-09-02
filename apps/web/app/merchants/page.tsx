"use client";

import { useEffect, useState, type FormEvent } from "react";

import {
  Button,
  Card,
  EmptyState,
  ErrorText,
  Input,
  Label,
  LoadingRow,
  SuccessText,
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
    <main className="max-w-2xl mx-auto px-6 py-10">
      <h1 className="text-xl font-semibold text-slate-900">Merchants</h1>
      <p className="text-sm text-slate-500 mt-1">
        Merchants are the tenant boundary every financial event attaches to.
      </p>

      <Card className="mt-8 p-5">
        <form onSubmit={handleCreate} className="space-y-4">
          <h2 className="font-medium text-sm text-slate-900">Create merchant</h2>
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
            <Label htmlFor="merchant-segment">Segment (optional)</Label>
            <Input
              id="merchant-segment"
              value={segment}
              onChange={(e) => setSegment(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={submitting || !name}>
            {submitting ? "Creating…" : "Create merchant"}
          </Button>
          {submitError && <ErrorText>{submitError}</ErrorText>}
          {submitSuccess && <SuccessText>{submitSuccess}</SuccessText>}
        </form>
      </Card>

      <div className="mt-8">
        <h2 className="font-medium text-sm text-slate-900 mb-3">All merchants</h2>
        {loading && <LoadingRow>Loading merchants…</LoadingRow>}
        {error && <ErrorText>{error}</ErrorText>}
        {!loading && !error && merchants.length === 0 && (
          <EmptyState>No merchants yet.</EmptyState>
        )}
        {!loading && merchants.length > 0 && (
          <Card>
            <ul className="divide-y divide-slate-100">
              {merchants.map((m) => (
                <li key={m.id} className="px-4 py-3.5 flex justify-between items-center text-sm">
                  <span className="text-slate-900 font-medium">
                    {m.name}
                    {m.segment ? (
                      <span className="text-slate-400 font-normal"> · {m.segment}</span>
                    ) : null}
                  </span>
                  <span className="text-slate-400 text-xs font-mono">{m.id}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </main>
  );
}
