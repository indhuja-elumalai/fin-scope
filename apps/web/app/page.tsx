"use client";

import { useEffect, useState } from "react";

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
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1.5rem", fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>FIN-SCOPE</h1>
      <p style={{ color: "#666", marginTop: "0.25rem" }}>System foundation status</p>

      <div style={{ marginTop: "2rem", border: "1px solid #e5e5e5", borderRadius: 8, padding: "1.25rem" }}>
        {loading && <p>Checking backend health…</p>}
        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
        {health && (
          <>
            <p style={{ fontWeight: 600, color: health.status === "ok" ? "#15803d" : "#b91c1c" }}>
              Overall: {health.status}
            </p>
            <ul style={{ marginTop: "0.75rem", paddingLeft: "1.25rem" }}>
              {Object.entries(health.checks).map(([name, check]) => (
                <li key={name}>
                  {name}: {check.status}
                  {check.detail ? ` — ${check.detail}` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </main>
  );
}
