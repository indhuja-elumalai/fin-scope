"use client";

// Top navigation. Split out from layout.tsx (a server component) because
// active-route highlighting needs usePathname(), which requires a client
// component -- keeping that boundary as small as possible rather than
// making the whole layout a client component.
//
// Fixes the previous contrast bug: inactive links used hardcoded
// text-neutral-600/900 with no dark-mode awareness, which was unreadable
// under the OS dark-mode media query the rest of the page no longer relies
// on (see globals.css). Colors here are chosen against the single
// slate-50/white theme globals.css now commits to, with an explicit active
// state (not just a hover state) so the current page is never ambiguous.
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/merchants", label: "Merchants" },
  { href: "/events", label: "Events" },
  { href: "/investigations", label: "Investigations" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="border-b border-slate-200 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/60 sticky top-0 z-10">
      <div className="max-w-5xl mx-auto px-6 h-14 flex items-center gap-1">
        <Link
          href="/"
          className="font-semibold text-slate-900 text-sm tracking-tight mr-4 flex items-center gap-1.5"
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-600" aria-hidden="true" />
          FIN-SCOPE
        </Link>
        {LINKS.map((link) => {
          const active = pathname === link.href || pathname?.startsWith(`${link.href}/`);
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
    </nav>
  );
}
