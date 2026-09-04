// Small, shared presentational primitives for the FIN-SCOPE frontend.
//
// Deliberately not a component library: no new dependency, no variant-prop
// framework, just the handful of patterns every page (merchants, events,
// investigations) already repeats -- cards, badges, buttons, form fields,
// empty states -- pulled into one place so they stay visually consistent
// and a future page does not reinvent (or subtly drift from) them.
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
  return (
    <div
      className={`bg-white border border-slate-200 rounded-xl shadow-sm ${className}`}
    >
      {children}
    </div>
  );
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
    <div className="flex items-baseline justify-between gap-4 flex-wrap">
      <div>
        {eyebrow && (
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-0.5">
            {eyebrow}
          </p>
        )}
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      </div>
      {children}
    </div>
  );
}

const BADGE_VARIANTS = {
  // FACT / INFERENCE / UNCERTAINTY -- the core distinction Phase 4 must
  // keep visible everywhere it applies (see README section 5).
  fact: "bg-slate-100 text-slate-700 border-slate-200",
  inference: "bg-indigo-50 text-indigo-700 border-indigo-200",
  uncertainty: "bg-amber-50 text-amber-800 border-amber-200",
  // Outcome/status colors.
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  danger: "bg-red-50 text-red-700 border-red-200",
  neutral: "bg-slate-100 text-slate-600 border-slate-200",
  // Confidence levels -- a bounded qualitative label, never a probability.
  high: "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-slate-100 text-slate-600 border-slate-200",
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
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${BADGE_VARIANTS[variant]}`}
    >
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
    "inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-medium px-4 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {
    primary: "bg-slate-900 text-white hover:bg-slate-800",
    secondary:
      "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
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
    <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700 mb-1">
      {children}
    </label>
  );
}

const FIELD_CLASSES =
  "w-full border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-900 bg-white " +
  "transition-shadow placeholder:text-slate-400 " +
  "hover:border-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none";

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
    <div className="text-center py-10 px-4 border border-dashed border-slate-200 rounded-lg">
      <p className="text-sm text-slate-500">{children}</p>
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin h-4 w-4 ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

export function LoadingRow({ children = "Loading…" }: { children?: ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 py-2">
      <Spinner />
      <span>{children}</span>
    </div>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
      {children}
    </p>
  );
}

export function SuccessText({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
      {children}
    </p>
  );
}

export function KeyValueRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="px-4 py-3 flex justify-between gap-4 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right text-slate-900 font-medium">{value}</dd>
    </div>
  );
}
// --- Application shell / command-center primitives -------------------
// Added for the product-ui-command-center pass. Deliberately still no new
// dependency: plain Tailwind + the existing Badge/Card patterns above.

export function EnvironmentBadge({
  health,
}: {
  health: "checking" | "ok" | "degraded" | "unreachable";
}) {
  const dot =
    health === "ok"
      ? "bg-emerald-500"
      : health === "degraded"
        ? "bg-amber-500"
        : health === "unreachable"
          ? "bg-red-500"
          : "bg-slate-300";
  const label =
    health === "ok"
      ? "API reachable"
      : health === "degraded"
        ? "API degraded"
        : health === "unreachable"
          ? "API unreachable"
          : "Checking API…";
  return (
    <div className="flex items-center gap-2">
      <span
        className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800"
        title="Razorpay TEST mode only -- this deployment has no production/live-money path (see README section 9)."
      >
        Test environment
      </span>
      <span className="flex items-center gap-1.5 text-xs text-slate-500">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${dot}`} aria-hidden="true" />
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
  return (
    <nav aria-label="Investigation workflow" className="overflow-x-auto">
      <ol className="flex items-center gap-0 min-w-max">
        {stages.map((stage, i) => {
          const isLast = i === stages.length - 1;
          const circle =
            stage.state === "done"
              ? "bg-slate-900 border-slate-900 text-white"
              : stage.state === "current"
                ? "bg-white border-slate-900 text-slate-900"
                : stage.state === "skipped"
                  ? "bg-white border-slate-200 text-slate-300"
                  : "bg-white border-slate-200 text-slate-400";
          const label =
            stage.state === "pending" || stage.state === "skipped"
              ? "text-slate-400"
              : "text-slate-900 font-medium";
          const content = (
            <div className="flex items-center gap-2 shrink-0">
              <span
                className={`flex items-center justify-center w-6 h-6 rounded-full border-2 text-[11px] font-semibold shrink-0 ${circle}`}
                aria-hidden="true"
              >
                {stage.state === "done" ? "✓" : i + 1}
              </span>
              <span className={`text-xs whitespace-nowrap ${label}`}>{stage.label}</span>
            </div>
          );
          return (
            <li key={stage.key} className="flex items-center shrink-0">
              {stage.href && stage.state !== "pending" ? (
                <a href={stage.href} className="rounded hover:opacity-70 transition-opacity">
                  {content}
                </a>
              ) : (
                content
              )}
              {!isLast && (
                <span
                  className={`w-6 sm:w-10 h-px mx-1.5 shrink-0 ${
                    stage.state === "done" ? "bg-slate-900" : "bg-slate-200"
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
  const dot = tone === "accent" ? "bg-blue-600" : "bg-slate-300";
  return (
    <li id={id} className="relative pl-6 pb-4 last:pb-0 scroll-mt-20">
      {!isLast && (
        <span
          className="absolute left-[5px] top-3 bottom-0 w-px bg-slate-200"
          aria-hidden="true"
        />
      )}
      <span
        className={`absolute left-0 top-1.5 w-[11px] h-[11px] rounded-full ring-4 ring-white ${dot}`}
        aria-hidden="true"
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">{title}</div>
        {trailing && <div className="shrink-0 text-right">{trailing}</div>}
      </div>
      {meta && <div className="text-xs text-slate-400 mt-0.5">{meta}</div>}
    </li>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "danger" | "success";
}) {
  const valueTone =
    tone === "danger" ? "text-red-700" : tone === "success" ? "text-emerald-700" : "text-slate-900";
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold tabular-nums ${valueTone}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
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
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div>
        {eyebrow && (
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400 mb-1">
            {eyebrow}
          </p>
        )}
        <h1 className="text-xl font-semibold text-slate-900 tracking-tight">{title}</h1>
        {description && <p className="text-sm text-slate-500 mt-1 max-w-2xl">{description}</p>}
      </div>
      {children && <div className="flex items-center gap-2 shrink-0">{children}</div>}
    </div>
  );
}
