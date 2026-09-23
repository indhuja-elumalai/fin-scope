"use client";

// Application shell navigation: grouped WORKFLOWS / DATA sections plus a
// live environment indicator. Split out from layout.tsx (a server
// component) because active-route highlighting needs usePathname(), which
// requires a client component -- keeping that boundary as small as possible
// rather than making the whole layout a client component.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { EnvironmentBadge } from "@/components/ui";

const WORKFLOWS = [
  { href: "/", label: "Command", code: "01", exact: true },
  { href: "/investigations", label: "Investigations", code: "02" },
];

const DATA_LINKS = [
  { href: "/merchants", label: "Merchants", code: "03" },
  { href: "/events", label: "Events", code: "04" },
];

type NavLink = { href: string; label: string; code: string; exact?: boolean };

function isActive(link: NavLink, pathname: string | null) {
  return link.exact
    ? pathname === link.href
    : pathname === link.href || !!pathname?.startsWith(`${link.href}/`);
}

// The FIN-SCOPE mark: a targeting reticle around a single "sensor" eye.
export function LogoMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden="true">
      <path d="M2 9V2h7M23 2h7v7M30 23v7h-7M9 30H2v-7" stroke="currentColor" strokeWidth="1.6" />
      <path d="M16 6l8.66 5v10L16 26l-8.66-5V11L16 6z" stroke="currentColor" strokeWidth="1.2" opacity="0.55" />
      <circle cx="16" cy="16" r="3.2" fill="currentColor" />
      <path d="M16 9v3M16 20v3M9 16h3M20 16h3" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function NavGroup({
  label,
  links,
  pathname,
}: {
  label: string;
  links: NavLink[];
  pathname: string | null;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="hidden lg:inline telemetry text-[9.5px] text-slate-300 mr-2 select-none">
        {label}
      </span>
      {links.map((link) => {
        const active = isActive(link, pathname);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={
              "group relative px-3 h-14 flex items-center gap-1.5 font-mono text-[11.5px] uppercase tracking-[0.12em] transition-colors " +
              (active ? "text-slate-950" : "text-slate-500 hover:text-slate-900")
            }
          >
            <span
              className={
                "text-[9.5px] tabular-nums " +
                (active ? "text-[var(--accent)]" : "text-slate-300 group-hover:text-slate-500")
              }
            >
              {link.code}
            </span>
            {link.label}
            <span
              className={
                "absolute left-2 right-2 bottom-0 h-[2px] transition-all " +
                (active
                  ? "bg-[var(--accent)] shadow-[0_0_12px_var(--accent)]"
                  : "bg-transparent group-hover:bg-slate-300")
              }
              aria-hidden="true"
            />
          </Link>
        );
      })}
    </div>
  );
}

export function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<"checking" | "ok" | "degraded" | "unreachable">(
    "checking"
  );

  // One real health check on mount -- reused by EnvironmentBadge in place
  // of a fabricated status. Deliberately no polling interval: a control
  // plane nav bar should not be silently hammering /health forever.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/health", { cache: "no-store" })
      .then((response) => response.json())
      .then((body: { status?: string }) => {
        if (cancelled) return;
        setHealth(body.status === "ok" ? "ok" : "degraded");
      })
      .catch(() => {
        if (!cancelled) setHealth("unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <nav className="sticky top-0 z-40 border-b border-slate-200 bg-[#05080c]/80 backdrop-blur-md">
      {/* Hairline "scan" highlight along the top edge. */}
      <div
        className="h-px bg-linear-to-r from-transparent via-[var(--accent)] to-transparent opacity-60"
        aria-hidden="true"
      />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2.5 shrink-0 group">
          <LogoMark className="w-7 h-7 text-[var(--accent)] drop-shadow-[0_0_8px_var(--accent-glow)] transition-transform group-hover:rotate-90 duration-500" />
          <span className="flex flex-col leading-none">
            <span className="font-[family-name:var(--font-display)] text-[15px] font-bold tracking-[0.18em] text-slate-950">
              FIN-SCOPE
            </span>
            <span className="hidden sm:block font-mono text-[8.5px] tracking-[0.22em] text-slate-400 mt-1">
              DECISION ENGINE
            </span>
          </span>
        </Link>

        <div className="hidden md:flex items-center gap-4 flex-1 min-w-0">
          <span className="w-px h-6 bg-slate-200" aria-hidden="true" />
          <NavGroup label="Ops" links={WORKFLOWS} pathname={pathname} />
          <span className="w-px h-6 bg-slate-200" aria-hidden="true" />
          <NavGroup label="Data" links={DATA_LINKS} pathname={pathname} />
        </div>

        {/* Compact link row for narrow viewports -- the grouped labels
            above are a desktop-first affordance, not the only way in. */}
        <div className="flex md:hidden items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-thin">
          {[...WORKFLOWS, ...DATA_LINKS].map((link) => {
            const active = isActive(link, pathname);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={
                  "px-2 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] whitespace-nowrap border transition-colors " +
                  (active
                    ? "border-sky-300 bg-sky-50 text-[var(--accent)]"
                    : "border-transparent text-slate-500 hover:text-slate-900")
                }
              >
                {link.label}
              </Link>
            );
          })}
        </div>

        <div className="shrink-0">
          <EnvironmentBadge health={health} />
        </div>
      </div>
    </nav>
  );
}
