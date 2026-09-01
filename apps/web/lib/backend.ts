// Server-only helper for calling the FIN-SCOPE backend API.
//
// Route handlers under app/api/* use this so the shared API key never
// reaches the browser -- it lives only in this server-side environment
// variable (API_KEY), never in a NEXT_PUBLIC_* one. This keeps the
// browser -> Next.js server -> FastAPI -> Postgres flow real end to end
// while keeping the secret where it belongs.
const BACKEND_URL = process.env.API_BASE_URL ?? "http://localhost:8000";
const BACKEND_API_KEY = process.env.API_KEY ?? "";

export async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", BACKEND_API_KEY);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${BACKEND_URL}${path}`, { ...init, headers, cache: "no-store" });
}
