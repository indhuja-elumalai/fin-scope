"use client";

// Command center: the investigation workflow's home screen. Every number
// on this page comes from an existing backend endpoint (merchants list,
// investigations list + its own `total`, and /api/health) -- nothing here is
// a fabricated metric or a client-side estimate presented as fact.
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  Card,
  ErrorText,
  Led,
  LoadingRow,
  PageHeader,
  SectionHeading,
  StatTile,
  Telemetry,
} from "@/components/ui";

type HealthCheck = { status: string; detail?: string };
// The backend reports subsystem state as flat top-level fields today
// (`{status, database: "up", redis: "up"}`); a nested `checks` map is also
// accepted so either shape renders.
type HealthResponse = {
  status: string;
  checks?: Record<string, HealthCheck>;
  [subsystem: string]: unknown;
};

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

// FIND -> ... -> VERIFY. Exactly one step is AI-assisted (reasoning); every
// other step is deterministic code (README sections 4 and 5).
const CONTROL_LOOP = [
  { code: "SRC", label: "Financial events", detail: "Ingested, idempotent", ai: false },
  { code: "FND", label: "Detect the anomaly", detail: "Threshold rule", ai: false },
  { code: "INV", label: "Investigate evidence", detail: "Dominant-signal heuristic", ai: false },
  { code: "RSN", label: "Reason about causes", detail: "Schema-validated hypotheses", ai: true },
  { code: "SIM", label: "Simulate consequences", detail: "Explicit assumptions", ai: false },
  { code: "POL", label: "Policy & authorization", detail: "Deterministic gate", ai: false },
  { code: "ACT", label: "Execute within bounds", detail: "Sandbox / Razorpay TEST", ai: false },
  { code: "VFY", label: "Verify the outcome", detail: "Expected vs. observed", ai: false },
];

const ROW_GRID = "grid grid-cols-[96px_minmax(0,1.6fr)_56px_minmax(0,1fr)_160px] items-center gap-3";

const COMMANDS = [
  { href: "/investigations", cmd: "run investigation", hint: "FIND → VERIFY on a merchant" },
  { href: "/events", cmd: "ingest event", hint: "Push or inspect financial events" },
  { href: "/merchants", cmd: "register merchant", hint: "Onboard a tenant boundary" },
];

function StatusDial({ state }: { state: "checking" | "ok" | "degraded" | "unreachable" }) {
  const color =
    state === "ok"
      ? "var(--ok)"
      : state === "checking"
        ? "var(--accent)"
        : state === "degraded"
          ? "var(--warn)"
          : "var(--danger)";
  return (
    <svg viewBox="0 0 120 120" className="w-full h-full" aria-hidden="true">
      <defs>
        <radialGradient id="dial-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="sweep-grad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={color} stopOpacity="0" />
          <stop offset="100%" stopColor={color} stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="56" fill="url(#dial-glow)" />
      {[52, 38, 24].map((r) => (
        <circle key={r} cx="60" cy="60" r={r} stroke={color} strokeOpacity="0.25" fill="none" />
      ))}
      <circle
        cx="60"
        cy="60"
        r="56"
        stroke={color}
        strokeOpacity="0.6"
        strokeWidth="1.5"
        fill="none"
        strokeDasharray="2 5"
      />
      <path d="M60 4v10M60 106v10M4 60h10M106 60h10" stroke={color} strokeOpacity="0.7" />
      <g className="sweep">
        <path d="M60 60 L112 60 A52 52 0 0 0 96.8 23.2 Z" fill="url(#sweep-grad)" />
      </g>
      <circle cx="60" cy="60" r="5" fill={color} />
      <circle cx="60" cy="60" r="9" stroke={color} strokeOpacity="0.5" fill="none" />
    </svg>
  );
}

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

    fetch("/api/health", { cache: "no-store" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Health check failed (${response.status})`);
        }
        return response.json() as Promise<HealthResponse>;
      })
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
        if (!cancelled) {
          setMerchantsError(
            err instanceof Error ? err.message : "Failed to load merchants."
          );
        }
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

  const systemTone =
    !health ? "neutral" : health.status === "ok" ? "success" : "danger";

  const dialState = health
    ? health.status === "ok"
      ? "ok"
      : "degraded"
    : healthError
      ? "unreachable"
      : "checking";

  const dialLabel = {
    ok: "All systems nominal",
    degraded: "Degraded",
    unreachable: "Link lost",
    checking: "Handshaking…",
  }[dialState];

  const healthChecks: [string, HealthCheck][] = !health
    ? []
    : health.checks
      ? Object.entries(health.checks)
      : Object.entries(health)
          .filter(([key, value]) => key !== "status" && typeof value === "string")
          .map(([key, value]) => [
            key,
            { status: String(value) },
          ]);

  return (
    <main className="max-w-6xl mx-auto px-4 sm:px-6 py-10">
      {/* --- Hero ------------------------------------------------------ */}
      <div className="grid lg:grid-cols-[1fr_320px] gap-6 items-stretch">
        <Card className="p-6 sm:p-8 overflow-hidden">
          <div
            className="absolute inset-0 pointer-events-none opacity-60 bg-[radial-gradient(ellipse_at_top_right,rgb(45_226_255/0.12),transparent_60%)]"
            aria-hidden="true"
          />
          <div className="relative">
            <PageHeader
              eyebrow="SYS://fin-scope/command"
              title={
                <>
                  Command <span className="text-[var(--accent)] text-glow">center</span>
                </>
              }
              description="Financial Intelligence, Simulation & Controlled Decision Engine. Detect, reason, simulate, gate, act and verify — every step bounded, auditable and replayable."
            />
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Link href="/investigations">
                <Button variant="primary">▶ Run investigation</Button>
              </Link>
              <Link href="/events">
                <Button variant="secondary">Inspect events</Button>
              </Link>
            </div>
            <div className="mt-8 pt-4 border-t border-dashed border-slate-200 flex flex-wrap gap-x-6 gap-y-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-slate-400">
              <span>
                <span className="text-[var(--accent)]">■</span> Deterministic core
              </span>
              <span>
                <span className="text-indigo-400">■</span> 1 AI step · proposal only
              </span>
              <span>
                <span className="text-amber-400">■</span> TEST-mode execution
              </span>
            </div>
          </div>
        </Card>

        <Card className="p-5 flex flex-col">
          <div className="flex items-center justify-between">
            <Telemetry slashes>System status</Telemetry>
            <Led
              tone={
                dialState === "ok"
                  ? "ok"
                  : dialState === "checking"
                    ? "accent"
                    : dialState === "degraded"
                      ? "warn"
                      : "danger"
              }
              pulse
            />
          </div>
          <div className="relative mx-auto my-4 w-36 h-36">
            <StatusDial state={dialState} />
          </div>
          <p className="text-center font-[family-name:var(--font-display)] text-lg font-semibold uppercase tracking-wider text-slate-900">
            {dialLabel}
          </p>
          <ul className="mt-4 space-y-1.5 font-mono text-[11px]">
            {healthChecks.length === 0 && (
              <li className="text-slate-400 text-center uppercase tracking-[0.12em] text-[10px]">
                {healthError ? "No telemetry" : "Awaiting telemetry"}
              </li>
            )}
            {healthChecks.map(([name, check]) => {
              const up = check.status === "ok" || check.status === "up";
              return (
                <li
                  key={name}
                  className="flex items-center justify-between gap-3 border-b border-slate-100 last:border-0 pb-1.5 last:pb-0"
                  title={check.detail}
                >
                  <span className="uppercase tracking-[0.1em] text-slate-500">{name}</span>
                  <span
                    className={`flex items-center gap-1.5 uppercase ${
                      up ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    <Led tone={up ? "ok" : "danger"} />
                    {check.status}
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      {/* --- Stat tiles ------------------------------------------------ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
        <StatTile index={1} label="Merchants" value={merchantCountLabel} hint="Onboarded merchants" />
        <StatTile
          index={2}
          label="Investigations"
          value={investigationsTotal ?? "—"}
          hint="All time, this environment"
        />
        <StatTile
          index={3}
          label="Incidents"
          value={incidentsTotal ?? "—"}
          tone={incidentsTotal && incidentsTotal > 0 ? "danger" : "neutral"}
          hint="Deterministic FIND threshold met"
        />
        <StatTile
          index={4}
          label="API"
          value={health ? health.status : healthError ? "offline" : "…"}
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

      <div className="grid lg:grid-cols-3 gap-6 mt-6">
        {/* --- Recent investigations ----------------------------------- */}
        <div className="lg:col-span-2 space-y-6 min-w-0">
          <Card className="p-5">
            <SectionHeading eyebrow="Activity log" title="Recent investigations">
              <Link
                href="/investigations"
                className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-[var(--accent)] hover:underline"
              >
                View all →
              </Link>
            </SectionHeading>

            {recent === null && !investigationsError && (
              <div className="pt-3">
                <LoadingRow>Loading recent investigations</LoadingRow>
              </div>
            )}

            {recent !== null && recent.length === 0 && (
              <p className="text-sm text-slate-500 py-8 text-center">
                No investigations yet — merchants and financial events are onboarded
                before an investigation can run.
              </p>
            )}

            {recent !== null && recent.length > 0 && (
              <div className="overflow-x-auto -mx-5">
                <div className="min-w-[560px]">
                  <div className={`${ROW_GRID} telemetry text-slate-400 px-5 py-2.5`}>
                    <span>Status</span>
                    <span>Merchant</span>
                    <span className="text-right">Events</span>
                    <span>Signal</span>
                    <span className="text-right">Timestamp</span>
                  </div>
                  <ul className="divide-y divide-slate-100 border-t border-slate-100">
                    {recent.map((inv) => (
                      <li key={inv.id}>
                        <Link
                          href={`/investigations/${inv.id}`}
                          className={`${ROW_GRID} group px-5 py-3 text-sm hover:bg-sky-50 transition-colors`}
                        >
                          <span>
                            <Badge variant={inv.incident_detected ? "danger" : "neutral"}>
                              {inv.incident_detected ? "Incident" : "Clear"}
                            </Badge>
                          </span>
                          <span className="text-slate-900 truncate">
                            {merchantNames.get(inv.merchant_id) ?? inv.merchant_id.slice(0, 8)}
                          </span>
                          <span className="text-right font-mono text-slate-700 tabular-nums">
                            {String(inv.evidence_event_count).padStart(3, "0")}
                          </span>
                          <span className="font-mono text-xs text-slate-500 truncate">
                            {inv.dominant_signal_event_type ?? "—"}
                          </span>
                          <span className="text-right font-mono text-[11px] text-slate-400 whitespace-nowrap">
                            {new Date(inv.created_at).toLocaleString()}
                            <span className="ml-2 text-[var(--accent)] opacity-0 group-hover:opacity-100 transition-opacity">
                              →
                            </span>
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </Card>

          {/* --- Command palette --------------------------------------- */}
          <div className="grid sm:grid-cols-3 gap-4">
            {COMMANDS.map((c) => (
              <Link key={c.href} href={c.href} className="group">
                <Card className="p-4 h-full transition-colors group-hover:bg-sky-50">
                  <p className="font-mono text-[13px] text-slate-900">
                    <span className="text-[var(--accent)]">&gt;</span> {c.cmd}
                    <span className="hidden group-hover:inline-block w-2 h-3.5 ml-1 align-middle bg-[var(--accent)] led-pulse" />
                  </p>
                  <p className="text-xs text-slate-400 mt-2">{c.hint}</p>
                </Card>
              </Link>
            ))}
          </div>
        </div>

        {/* --- Control loop ------------------------------------------- */}
        <Card className="p-5">
          <SectionHeading eyebrow="Signal → safe action" title="Control loop" />
          <ol className="mt-4">
            {CONTROL_LOOP.map((step, i) => {
              const isLast = i === CONTROL_LOOP.length - 1;
              return (
                <li key={step.code} className="relative flex gap-3 pb-3 last:pb-0">
                  {!isLast && (
                    <span
                      className={`absolute left-[17px] top-9 bottom-0 w-px ${
                        step.ai || CONTROL_LOOP[i + 1].ai ? "bg-indigo-300" : "bg-slate-300"
                      }`}
                      aria-hidden="true"
                    >
                      <span className="absolute inset-0 flow-line opacity-70" />
                    </span>
                  )}
                  <span
                    className={`chamfer-sm shrink-0 w-9 h-9 flex items-center justify-center border font-mono text-[9.5px] font-semibold tracking-wider ${
                      step.ai
                        ? "border-indigo-400 bg-indigo-100 text-indigo-700 shadow-[0_0_16px_-2px_rgb(167_139_250/0.6)]"
                        : "border-slate-300 bg-slate-50 text-[var(--accent)]"
                    }`}
                  >
                    {step.code}
                  </span>
                  <div className="min-w-0 pt-0.5">
                    <p
                      className={`text-[13px] leading-tight ${
                        step.ai ? "text-indigo-700 font-medium" : "text-slate-800"
                      }`}
                    >
                      {step.label}
                    </p>
                    <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-slate-400 mt-1">
                      {step.ai ? "AI · " : "DET · "}
                      {step.detail}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
          <p className="text-xs text-slate-500 mt-5 pt-4 border-t border-dashed border-slate-200 leading-relaxed">
            No black-box actions. The model proposes; deterministic code decides, executes and
            verifies.
          </p>
        </Card>
      </div>
    </main>
  );
}
