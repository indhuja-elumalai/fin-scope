"use client";

import { useEffect, useState } from "react";

import { Card, ErrorText, LoadingRow } from "@/components/ui";

type HealthCheck = { status: string; detail?: string };
type HealthResponse = { status: string; checks: Record<string, HealthCheck> };

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HealthStatusPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchHealth() {
      try {
        const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
        const body = (await response.json()) as HealthResponse;
        if (!cancelled) {
          setHealth(body);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("Could not reach the FIN-SCOPE API.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="max-w-2xl mx-auto px-6 py-10">
      <h1 className="text-xl font-semibold text-slate-900">FIN-SCOPE</h1>
      <p className="text-sm text-slate-500 mt-1">
        Financial Intelligence, Simulation &amp; Controlled Decision Engine — system foundation
        status.
      </p>

      <Card className="mt-8 p-5">
        {loading && <LoadingRow>Checking backend health…</LoadingRow>}
        {error && <ErrorText>{error}</ErrorText>}
        {health && (
          <>
            <div className="flex items-center gap-2">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  health.status === "ok" ? "bg-emerald-500" : "bg-red-500"
                }`}
                aria-hidden="true"
              />
              <p
                className={`font-semibold text-sm ${
                  health.status === "ok" ? "text-emerald-700" : "text-red-700"
                }`}
              >
                Overall: {health.status}
              </p>
            </div>
            <ul className="mt-4 divide-y divide-slate-100">
              {Object.entries(health.checks).map(([name, check]) => (
                <li key={name} className="py-2 flex justify-between text-sm">
                  <span className="text-slate-600">{name}</span>
                  <span className="text-slate-900">
                    {check.status}
                    {check.detail ? (
                      <span className="text-slate-400"> — {check.detail}</span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </main>
  );
}
