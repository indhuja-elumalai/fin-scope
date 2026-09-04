"use client";

// Application shell navigation: grouped WORKFLOWS / DATA sections plus a
// live environment indicator, replacing the earlier flat link row. Split
// out from layout.tsx (a server component) because active-route
// highlighting needs usePathname(), which requires a client component --
// keeping that boundary as small as possible rather than making the whole
// layout a client component.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { EnvironmentBadge } from "@/components/ui";

const WORKFLOWS = [
  { href: "/", label: "Command center", exact: true },
  { href: "/investigations", label: "Investigations" },
];

const DATA_LINKS = [
  { href: "/merchants", label: "Merchants" },
  { href: "/events", label: "Events" },
];

function NavGroup({
  label,
  links,
  pathname,
}: {
  label: string;
  links: { href: string; label: string; exact?: boolean }[];
  pathname: string | null;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="hidden lg:inline text-[10px] font-semibold uppercase tracking-wider text-slate-300 mr-1.5 select-none">
        {label}
      </span>
      {links.map((link) => {
        const active = link.exact
          ? pathname === link.href
          : pathname === link.href || pathname?.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={
              "px-3 py-1.5 rounded-md text-sm font-medium transition-colors " +
              (active
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:text-slate-900 hover:bg-slate-100")
            }
          >
            {link.label}
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
    <nav className="border-b border-slate-200 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/60 sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-5">
        <Link
          href="/"
          className="font-semibold text-slate-900 text-sm tracking-tight flex items-center gap-1.5 shrink-0"
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-600" aria-hidden="true" />
          FIN-SCOPE
        </Link>

        <div className="hidden md:flex items-center gap-5 flex-1 min-w-0">
          <NavGroup label="Workflows" links={WORKFLOWS} pathname={pathname} />
          <span className="w-px h-5 bg-slate-200" aria-hidden="true" />
          <NavGroup label="Data" links={DATA_LINKS} pathname={pathname} />
        </div>

        {/* Compact link row for narrow viewports -- the grouped labels
            above are a desktop-first affordance, not the only way in. */}
        <div className="flex md:hidden items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-thin">
          {[...WORKFLOWS, ...DATA_LINKS].map((link) => {
            const active =
              "exact" in link && link.exact
                ? pathname === link.href
                : pathname === link.href || pathname?.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={
                  "px-2.5 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors " +
                  (active
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-100")
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
