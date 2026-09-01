"use client";

import { useEffect, useState, type FormEvent } from "react";

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
    <main className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-xl font-semibold">Merchants</h1>
      <p className="text-sm text-neutral-500 mt-1">
        Merchants are the tenant boundary every financial event attaches to.
      </p>

      <form
        onSubmit={handleCreate}
        className="mt-8 border border-neutral-200 rounded-lg p-5 space-y-3"
      >
        <h2 className="font-medium text-sm">Create merchant</h2>
        <div>
          <label className="block text-sm text-neutral-600" htmlFor="merchant-name">
            Name
          </label>
          <input
            id="merchant-name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm text-neutral-600" htmlFor="merchant-segment">
            Segment (optional)
          </label>
          <input
            id="merchant-segment"
            value={segment}
            onChange={(e) => setSegment(e.target.value)}
            className="mt-1 w-full border border-neutral-300 rounded px-3 py-1.5 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={submitting || !name}
          className="bg-neutral-900 text-white text-sm rounded px-4 py-1.5 disabled:opacity-50"
        >
          {submitting ? "Creating…" : "Create merchant"}
        </button>
        {submitError && <p className="text-sm text-red-600">{submitError}</p>}
        {submitSuccess && <p className="text-sm text-green-700">{submitSuccess}</p>}
      </form>

      <div className="mt-8">
        <h2 className="font-medium text-sm mb-3">All merchants</h2>
        {loading && <p className="text-sm text-neutral-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && merchants.length === 0 && (
          <p className="text-sm text-neutral-500">No merchants yet.</p>
        )}
        {!loading && merchants.length > 0 && (
          <ul className="divide-y divide-neutral-200 border border-neutral-200 rounded-lg">
            {merchants.map((m) => (
              <li key={m.id} className="px-4 py-3 text-sm flex justify-between">
                <span>
                  {m.name}
                  {m.segment ? <span className="text-neutral-400"> · {m.segment}</span> : null}
                </span>
                <span className="text-neutral-400 text-xs">{m.id}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
