"use client";

// Command center: the investigation workflow's home screen. Every number
// on this page comes from an existing backend endpoint (merchants list,
// investigations list + its own `total`, and /health) -- nothing here is
// a fabricated metric or a client-side estimate presented as fact.
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  ErrorText,
  LoadingRow,
  PageHeader,
  StatTile,
} from "@/components/ui";

type HealthCheck = { status: string; detail?: string };
type HealthResponse = { status: string; checks: Record<string, HealthCheck> };

type Merchant = { id: string; name: string };

type Investigation = {
  id: string;
  merchant_id: string;
  incident_detected: boolean;
  evidence_event_count: number;
  dominant_signal_event_type: string | null;
  created_at: string;
};

type InvestigationListResponse = { items: Investigation[]; total: number };

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function CommandCenterPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [merchants, setMerchants] = useState<Merchant[] | null>(null);
  const [merchantsError, setMerchantsError] = useState<string | null>(null);

  const [investigationsTotal, setInvestigationsTotal] = useState<number | null>(null);
  const [incidentsTotal, setIncidentsTotal] = useState<number | null>(null);
  const [recent, setRecent] = useState<Investigation[] | null>(null);
  const [investigationsError, setInvestigationsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE_URL}/health`, { cache: "no-store" })
      .then((response) => response.json() as Promise<HealthResponse>)
      .then((body) => {
        if (!cancelled) setHealth(body);
      })
      .catch(() => {
        if (!cancelled) setHealthError("Could not reach the FIN-SCOPE API.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/merchants?limit=200")
      .then((response) => {
        if (!response.ok) throw new Error(`Failed to load merchants (${response.status})`);
        return response.json() as Promise<Merchant[]>;
      })
      .then((body) => {
        if (!cancelled) setMerchants(body);
      })
      .catch((err) => {
        if (!cancelled)
          setMerchantsError(err instanceof Error ? err.message : "Failed to load merchants.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [totalRes, incidentRes, recentRes] = await Promise.all([
          fetch("/api/investigations?limit=1"),
          fetch("/api/investigations?incident_detected=true&limit=1"),
          fetch("/api/investigations?limit=6"),
        ]);
        if (!totalRes.ok || !incidentRes.ok || !recentRes.ok) {
          throw new Error("Failed to load investigation summary.");
        }
        const [totalBody, incidentBody, recentBody] = (await Promise.all([
          totalRes.json(),
          incidentRes.json(),
          recentRes.json(),
        ])) as InvestigationListResponse[];
        if (cancelled) return;
        setInvestigationsTotal(totalBody.total);
        setIncidentsTotal(incidentBody.total);
        setRecent(recentBody.items);
      } catch (err) {
        if (!cancelled) {
          setInvestigationsError(
            err instanceof Error ? err.message : "Failed to load investigation summary."
          );
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const merchantNames = new Map((merchants ?? []).map((m) => [m.id, m.name]));
  const merchantCountLabel =
    merchants === null
      ? "—"
      : merchants.length === 200
        ? "200+"
        : String(merchants.length);

  const systemTone = !health ? "neutral" : health.status === "ok" ? "success" : "danger";

  return (
    <main className="max-w-6xl mx-auto px-6 py-10">
      <PageHeader
        eyebrow="FIN-SCOPE"
        title="Command center"
        description="Financial Intelligence, Simulation & Controlled Decision Engine — the FIND → REASON → IMPACT → SIMULATE → DECIDE → POLICY → ACT → VERIFY workflow, in one place."
      >
        <Link href="/investigations">
          <Button variant="primary">Run investigation</Button>
        </Link>
      </PageHeader>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
        <StatTile label="Merchants" value={merchantCountLabel} hint="Onboarded merchants" />
        <StatTile
          label="Investigations"
          value={investigationsTotal ?? "—"}
          hint="All time, this environment"
        />
        <StatTile
          label="Incidents detected"
          value={incidentsTotal ?? "—"}
          tone={incidentsTotal && incidentsTotal > 0 ? "danger" : "neutral"}
          hint="Deterministic FIND threshold met"
        />
        <StatTile
          label="System"
          value={health ? health.status : healthError ? "unreachable" : "…"}
          tone={systemTone}
          hint="Live backend health check"
        />
      </div>

      {(merchantsError || investigationsError || healthError) && (
        <div className="mt-4 space-y-2">
          {merchantsError && <ErrorText>{merchantsError}</ErrorText>}
          {investigationsError && <ErrorText>{investigationsError}</ErrorText>}
          {healthError && <ErrorText>{healthError}</ErrorText>}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6 mt-8">
        <div className="lg:col-span-2">
          <Card className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-900">Recent investigations</h2>
              <Link
                href="/investigations"
                className="text-xs text-blue-600 hover:underline font-medium"
              >
                View all
              </Link>
            </div>

            {recent === null && !investigationsError && (
              <LoadingRow>Loading recent investigations…</LoadingRow>
            )}
            {recent !== null && recent.length === 0 && (
              <p className="text-sm text-slate-500 py-6 text-center">
                No investigations yet — merchants and financial events are onboarded before an
                investigation can run.
              </p>
            )}
            {recent !== null && recent.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {recent.map((inv) => (
                  <li key={inv.id}>
                    <Link
                      href={`/investigations/${inv.id}`}
                      className="py-3 flex items-center justify-between gap-4 hover:bg-slate-50 -mx-2 px-2 rounded-lg transition-colors"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Badge variant={inv.incident_detected ? "danger" : "neutral"}>
                          {inv.incident_detected ? "Incident" : "No incident"}
                        </Badge>
                        <div className="min-w-0">
                          <div className="text-sm text-slate-800 truncate">
                            {merchantNames.get(inv.merchant_id) ?? inv.merchant_id.slice(0, 8)}
                          </div>
                          <div className="text-xs text-slate-400 truncate">
                            {inv.evidence_event_count} events ·{" "}
                            {new Date(inv.created_at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                      <span className="text-slate-400 text-xs shrink-0">
                        {inv.dominant_signal_event_type ?? "—"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-4">
            <h2 className="text-sm font-semibold text-slate-900 mb-1">Workflow</h2>
            <p className="text-xs text-slate-500 mb-3">
              Every investigation moves through the same deterministic-and-AI pipeline.
            </p>
            <ol className="space-y-1.5 text-xs text-slate-600">
              {[
                "FIND — rule-based incident detection",
                "REASON — evidence-grounded AI hypotheses",
                "IMPACT — currency-safe financial exposure",
                "SIMULATE — deterministic scenario projection",
                "DECIDE — preferred-scenario comparison",
                "POLICY — autonomous-action authorization",
                "ACT — bounded sandbox or Razorpay TEST",
                "VERIFY — expected vs. observed outcome",
              ].map((step, i) => (
                <li key={step} className="flex gap-2">
                  <span className="text-slate-300 tabular-nums w-3 shrink-0">{i + 1}</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </Card>

          <Card className="p-4">
            <h2 className="text-sm font-semibold text-slate-900 mb-3">Quick links</h2>
            <div className="flex flex-col gap-2">
              <Link
                href="/merchants"
                className="text-sm text-slate-700 hover:text-blue-600 transition-colors"
              >
                Manage merchants →
              </Link>
              <Link
                href="/events"
                className="text-sm text-slate-700 hover:text-blue-600 transition-colors"
              >
                Ingest / inspect financial events →
              </Link>
              <Link
                href="/investigations"
                className="text-sm text-slate-700 hover:text-blue-600 transition-colors"
              >
                Run a new investigation →
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}
