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
