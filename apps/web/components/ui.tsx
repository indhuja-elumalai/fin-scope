// Small, shared presentational primitives for the FIN-SCOPE frontend.
//
// Deliberately not a component library: no new dependency, no variant-prop
// framework, just the handful of patterns every page (merchants, events,
// investigations) already repeats -- cards, badges, buttons, form fields,
// empty states -- pulled into one place so they stay visually consistent
// and a future page does not reinvent (or subtly drift from) them.
//
// Visual language ("machine console"): bracketed HUD panels, chamfered
// controls, mono telemetry labels and status LEDs. The HUD classes
// (.hud-panel, .chamfer, .telemetry, .led) live in app/globals.css.
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`hud-panel ${className}`}>{children}</div>;
}

// Mono uppercase micro-label. `slashes` prefixes the "//" console marker.
export function Telemetry({
  children,
  className = "",
  slashes = false,
}: {
  children: ReactNode;
  className?: string;
  slashes?: boolean;
}) {
  return (
    <span className={`telemetry text-slate-400 ${className}`}>
      {slashes && (
        <span className="text-[var(--accent)] mr-1.5" aria-hidden="true">
          {"//"}
        </span>
      )}
      {children}
    </span>
  );
}

export function Led({
  tone = "neutral",
  pulse = false,
}: {
  tone?: "ok" | "warn" | "danger" | "accent" | "ai" | "neutral";
  pulse?: boolean;
}) {
  const color = {
    ok: "text-emerald-400",
    warn: "text-amber-400",
    danger: "text-red-400",
    accent: "text-sky-400",
    ai: "text-indigo-400",
    neutral: "text-slate-400",
  }[tone];
  return <span className={`led ${color} ${pulse ? "led-pulse" : ""}`} aria-hidden="true" />;
}

export function SectionHeading({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap pb-3 mb-1 border-b border-dashed border-slate-200">
      <div>
        {eyebrow && (
          <p className="mb-1">
            <Telemetry slashes>{eyebrow}</Telemetry>
          </p>
        )}
        <h2 className="font-[family-name:var(--font-display)] text-base font-semibold tracking-wide text-slate-900 uppercase">
          {title}
        </h2>
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </div>
  );
}

const BADGE_VARIANTS = {
  // FACT / INFERENCE / UNCERTAINTY -- the core distinction Phase 4 must
  // keep visible everywhere it applies (see README section 5).
  fact: "bg-slate-100 text-slate-700 border-slate-300",
  inference: "bg-indigo-50 text-indigo-700 border-indigo-200",
  uncertainty: "bg-amber-50 text-amber-800 border-amber-200",
  // Outcome/status colors.
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  danger: "bg-red-50 text-red-700 border-red-200",
  neutral: "bg-slate-100 text-slate-600 border-slate-300",
  // Confidence levels -- a bounded qualitative label, never a probability.
  high: "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-slate-100 text-slate-600 border-slate-300",
  // Phase 5 (deterministic simulation): a projected/simulated number is
  // visually distinct from both FACT and INFERENCE -- it is neither an
  // observed fact nor an AI judgment, it is a deterministic calculation
  // applied to an explicit assumption. See app.domain.simulation.
  projected: "bg-purple-50 text-purple-700 border-purple-200",
  assumption: "bg-amber-50 text-amber-800 border-amber-200",
  // Phase 6 (decision evaluation + policy): the preferred-scenario callout
  // is neither FACT, INFERENCE, nor PROJECTED -- it is a deterministic
  // comparison outcome. See app.domain.decision_evaluation. The three
  // policy outcomes get their own colors so ALLOWED /
  // REQUIRES_HUMAN_APPROVAL / BLOCKED are distinguishable at a glance,
  // independent of the DECISION badge above them.
  decision: "bg-sky-50 text-sky-700 border-sky-200",
  allowed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  requires_approval: "bg-amber-50 text-amber-800 border-amber-200",
  blocked: "bg-red-50 text-red-700 border-red-200",
  // Phase 7 (bounded sandbox action): every sandbox action result must be
  // visually distinguishable from a real financial action. This is the
  // ONLY new variant Phase 7 adds -- executed/rejected status reuses the
  // existing allowed/blocked colors above. See app.domain.sandbox_executor.
  sandbox: "bg-teal-50 text-teal-700 border-teal-200",
  // Phase 8 (outcome verification): the section-level badge distinguishing
  // "this is the deterministic verification result" from the EXPECTED
  // (projected, purple) and OBSERVED (sandbox, teal) values it compares.
  // The ONLY new variant Phase 8 adds -- VERIFIED_SUCCESS/PARTIALLY_VERIFIED/
  // FAILED/INSUFFICIENT_OBSERVATION reuse allowed/requires_approval/blocked/
  // neutral respectively. See app.domain.outcome_verification.
  verification: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  // Phase 10 (Razorpay TEST integration): a REAL network call to
  // Razorpay's TEST API -- structurally different from Phase 7's
  // in-process "sandbox" simulation (teal, above), so it gets its own
  // color rather than reusing "sandbox" and implying the same thing.
  // Still clearly TEST-mode, never a production/live-money color.
  razorpay: "bg-orange-50 text-orange-700 border-orange-200",
} as const;

export function Badge({
  variant = "neutral",
  children,
}: {
  variant?: keyof typeof BADGE_VARIANTS;
  children: ReactNode;
}) {
  return (
    <span
      className={`chamfer-sm inline-flex items-center gap-1.5 border px-2 py-[3px] font-mono text-[10.5px] font-medium uppercase tracking-[0.1em] leading-none whitespace-nowrap ${BADGE_VARIANTS[variant]}`}
    >
      <span className="w-1 h-1 bg-current opacity-80" aria-hidden="true" />
      {children}
    </span>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  const base =
    "chamfer relative inline-flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-[0.12em] px-5 py-2.5 transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none cursor-pointer";
  const variants = {
    primary:
      "bg-[var(--accent)] text-[#031018] hover:bg-[#7cefff] shadow-[0_0_24px_-4px_var(--accent-glow)] hover:shadow-[0_0_32px_-2px_var(--accent-glow)] active:translate-y-px",
    secondary:
      "bg-sky-50 text-sky-700 border border-sky-200 hover:bg-sky-100 hover:border-sky-300",
    ghost: "text-slate-600 hover:text-slate-900 hover:bg-slate-100",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function Label({
  children,
  htmlFor,
}: {
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <label htmlFor={htmlFor} className="telemetry block text-slate-500 mb-1.5">
      {children}
    </label>
  );
}

const FIELD_CLASSES =
  "w-full border border-slate-300 bg-[#070c12] px-3 py-2.5 text-sm font-mono text-slate-900 " +
  "transition-[border-color,box-shadow] placeholder:text-slate-400 " +
  "hover:border-slate-400 focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_rgb(45_226_255/0.12),0_0_18px_-6px_var(--accent-glow)] outline-none";

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", ...rest } = props;
  return <select className={`${FIELD_CLASSES} ${className}`} {...rest} />;
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return <input className={`${FIELD_CLASSES} ${className}`} {...rest} />;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="relative text-center py-12 px-4 border border-dashed border-slate-300 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_8px,rgb(255_255_255/0.015)_8px,rgb(255_255_255/0.015)_16px)]">
      <p className="telemetry text-slate-400 mb-2">
        <span className="text-amber-400">■</span> No signal
      </p>
      <p className="text-sm text-slate-500">{children}</p>
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin h-4 w-4 text-[var(--accent)] ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle className="opacity-20" cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
      <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
    </svg>
  );
}

export function LoadingRow({ children = "Loading…" }: { children?: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 py-2 font-mono text-xs uppercase tracking-[0.12em] text-slate-500">
      <Spinner />
      <span className="cursor-blink">{children}</span>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2.5 text-sm text-red-700 bg-red-50 border border-red-200 border-l-2 border-l-red-400 px-3 py-2.5">
      <span className="font-mono text-[10.5px] font-semibold tracking-[0.14em] text-red-400 pt-0.5 shrink-0">
        ERR
      </span>
      <span>{children}</span>
    </p>
  );
}

export function SuccessText({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2.5 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 border-l-2 border-l-emerald-400 px-3 py-2.5">
      <span className="font-mono text-[10.5px] font-semibold tracking-[0.14em] text-emerald-400 pt-0.5 shrink-0">
        OK
      </span>
      <span>{children}</span>
    </p>
  );
}

export function KeyValueRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="px-4 py-3 flex justify-between items-baseline gap-4 text-sm">
      <dt className="telemetry text-slate-400 shrink-0">{label}</dt>
      <dd className="text-right text-slate-900 font-mono text-[13px] break-all">{value}</dd>
    </div>
  );
}
// --- Application shell / command-center primitives -------------------

export function EnvironmentBadge({
  health,
}: {
  health: "checking" | "ok" | "degraded" | "unreachable";
}) {
  const tone =
    health === "ok"
      ? "ok"
      : health === "degraded"
        ? "warn"
        : health === "unreachable"
          ? "danger"
          : "neutral";
  const label =
    health === "ok"
      ? "API online"
      : health === "degraded"
        ? "API degraded"
        : health === "unreachable"
          ? "API offline"
          : "Handshake…";
  return (
    <div className="flex items-center gap-3">
      <span
        className="chamfer-sm hidden sm:inline-flex items-center gap-1.5 border border-amber-200 bg-amber-50 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-700"
        title="Razorpay TEST mode only -- this deployment has no production/live-money path (see README section 9)."
      >
        <span className="w-1 h-1 bg-current" aria-hidden="true" />
        Test env
      </span>
      <span className="flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-slate-500">
        <Led tone={tone} pulse={health === "ok" || health === "checking"} />
        <span className="sr-only sm:not-sr-only">{label}</span>
      </span>
    </div>
  );
}

export type WorkflowStageState = "done" | "current" | "pending" | "skipped";

export type WorkflowStage = {
  key: string;
  label: string;
  state: WorkflowStageState;
  href?: string;
};

// FIND -> REASON -> IMPACT -> SIMULATE -> DECIDE -> POLICY -> ACT -> VERIFY
// (README section 3 / section 12). Purely presentational -- the caller
// computes each stage's state from data it already fetched; this component
// invents nothing and calls no endpoint.
export function WorkflowStepper({ stages }: { stages: WorkflowStage[] }) {
  const doneCount = stages.filter((s) => s.state === "done").length;
  return (
    <nav aria-label="Investigation workflow" className="overflow-x-auto">
      <div className="flex items-center justify-between mb-3 min-w-max gap-6">
        <Telemetry slashes>Control loop</Telemetry>
        <span className="font-mono text-[10.5px] tracking-[0.12em] text-slate-500 tabular-nums">
          {String(doneCount).padStart(2, "0")}/{String(stages.length).padStart(2, "0")} stages
          complete
        </span>
      </div>
      <ol className="flex items-center gap-0 min-w-max">
        {stages.map((stage, i) => {
          const isLast = i === stages.length - 1;
          const node =
            stage.state === "done"
              ? "bg-sky-100 border-[var(--accent)] text-[var(--accent)] shadow-[0_0_14px_-2px_var(--accent-glow)]"
              : stage.state === "current"
                ? "bg-transparent border-[var(--accent)] text-[var(--accent)] led-pulse"
                : stage.state === "skipped"
                  ? "bg-transparent border-slate-200 text-slate-300"
                  : "bg-transparent border-slate-300 border-dashed text-slate-400";
          const label =
            stage.state === "pending" || stage.state === "skipped"
              ? "text-slate-400"
              : "text-slate-900";
          const content = (
            <div className="flex flex-col items-center gap-1.5 shrink-0 w-[72px]">
              <span
                className={`chamfer-sm flex items-center justify-center w-8 h-8 border font-mono text-[11px] font-semibold shrink-0 ${node}`}
                aria-hidden="true"
              >
                {stage.state === "done" ? "✓" : String(i + 1).padStart(2, "0")}
              </span>
              <span
                className={`font-mono text-[10px] uppercase tracking-[0.14em] whitespace-nowrap ${label}`}
              >
                {stage.label}
              </span>
            </div>
          );
          return (
            <li key={stage.key} className="flex items-start shrink-0">
              {stage.href && stage.state !== "pending" ? (
                <a href={stage.href} className="hover:opacity-70 transition-opacity">
                  {content}
                </a>
              ) : (
                content
              )}
              {!isLast && (
                <span
                  className={`w-5 sm:w-8 h-px mt-4 shrink-0 ${
                    stage.state === "done"
                      ? "bg-[var(--accent)] shadow-[0_0_6px_var(--accent)]"
                      : "bg-[repeating-linear-gradient(90deg,var(--border-strong)_0,var(--border-strong)_3px,transparent_3px,transparent_6px)]"
                  }`}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function Timeline({ children }: { children: ReactNode }) {
  return (
    <ol role="list" className="relative">
      {children}
    </ol>
  );
}

export function TimelineItem({
  title,
  meta,
  trailing,
  isLast = false,
  tone = "neutral",
  id,
}: {
  title: ReactNode;
  meta?: ReactNode;
  trailing?: ReactNode;
  isLast?: boolean;
  tone?: "neutral" | "accent";
  id?: string;
}) {
  const node =
    tone === "accent"
      ? "bg-[var(--accent)] border-[var(--accent)] shadow-[0_0_10px_var(--accent)]"
      : "bg-[var(--background)] border-slate-400";
  return (
    <li
      id={id}
      className="relative pl-7 pb-4 last:pb-0 scroll-mt-24 target:[&>div]:text-[var(--accent)]"
    >
      {!isLast && (
        <span
          className="absolute left-[4px] top-3.5 bottom-0 w-px bg-slate-300"
          aria-hidden="true"
        />
      )}
      <span
        className={`absolute left-0 top-1.5 w-[9px] h-[9px] rotate-45 border ${node}`}
        aria-hidden="true"
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">{title}</div>
        {trailing && <div className="shrink-0 text-right font-mono">{trailing}</div>}
      </div>
      {meta && <div className="font-mono text-[11px] text-slate-400 mt-0.5">{meta}</div>}
    </li>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  index,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "danger" | "success";
  index?: number;
}) {
  const valueTone =
    tone === "danger"
      ? "text-red-500 [text-shadow:0_0_20px_rgb(255_77_94/0.45)]"
      : tone === "success"
        ? "text-emerald-500 [text-shadow:0_0_20px_rgb(46_229_157/0.4)]"
        : "text-slate-900";
  const bar =
    tone === "danger" ? "bg-red-400" : tone === "success" ? "bg-emerald-400" : "bg-[var(--accent)]";
  return (
    <Card className="p-4 overflow-hidden group">
      <div className="flex items-center justify-between">
        <Telemetry>{label}</Telemetry>
        {index !== undefined && (
          <span className="font-mono text-[10px] text-slate-300 tabular-nums">
            {String(index).padStart(2, "0")}
          </span>
        )}
      </div>
      <p
        className={`mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold tabular-nums tracking-tight uppercase ${valueTone}`}
      >
        {value}
      </p>
      {hint && <p className="mt-1.5 text-xs text-slate-400">{hint}</p>}
      <span
        className={`absolute left-0 bottom-0 h-[2px] w-10 ${bar} opacity-80 transition-all duration-300 group-hover:w-full`}
        aria-hidden="true"
      />
    </Card>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="boot-in flex items-end justify-between gap-4 flex-wrap">
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-2 flex items-center gap-2">
            <span className="w-6 h-px bg-[var(--accent)]" aria-hidden="true" />
            <Telemetry className="text-[var(--accent)]">{eyebrow}</Telemetry>
          </p>
        )}
        <h1 className="font-[family-name:var(--font-display)] text-3xl sm:text-4xl font-semibold text-slate-900 tracking-tight uppercase">
          {title}
        </h1>
        {description && (
          <p className="text-sm text-slate-500 mt-2 max-w-2xl leading-relaxed">{description}</p>
        )}
      </div>
      {children && <div className="flex items-center gap-3 shrink-0">{children}</div>}
    </div>
  );
}
