"use client";

// Bottom telemetry strip: a live UTC clock and the fixed guarantees this
// deployment makes (TEST mode only, deterministic policy gate). Nothing here
// is a fabricated metric -- the clock is the browser's own time and the
// rest are static facts about the system (see README sections 5 and 9).
import { useEffect, useState } from "react";

function formatUtc(date: Date) {
  return date.toISOString().replace("T", " ").slice(0, 19);
}

export function StatusBar() {
  // Rendered only after mount so server and client HTML agree.
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const tick = () => setNow(new Date());
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <footer className="mt-16 border-t border-slate-200 bg-[#05080c]/90">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-9 flex items-center gap-5 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-400 overflow-x-auto scrollbar-thin whitespace-nowrap">
        <span className="flex items-center gap-1.5">
          <span className="text-[var(--accent)]">■</span> FIN-SCOPE
        </span>
        <span className="hidden sm:inline">Policy gate: deterministic</span>
        <span className="hidden sm:inline">AI → proposal only</span>
        <span className="text-amber-500">Razorpay: test mode</span>
        <span className="ml-auto tabular-nums text-slate-500">
          {now ? `${formatUtc(now)} UTC` : "—"}
        </span>
      </div>
    </footer>
  );
}
