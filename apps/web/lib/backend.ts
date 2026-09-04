// Server-only helper for calling the FIN-SCOPE backend API.
//
// Route handlers under app/api/* use this helper so the shared API key
// never reaches the browser. API_KEY is server-side only.
//
// Production:
//   Vercel → Render FastAPI
//
// Local development:
//   Next.js → localhost:8000
//
// IMPORTANT:
// Do not use NEXT_PUBLIC_API_KEY. The API key must remain server-side.

const BACKEND_URL =
  process.env.API_BASE_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : undefined);

const BACKEND_API_KEY = process.env.API_KEY ?? "";

if (!BACKEND_URL) {
  throw new Error(
    "FIN-SCOPE backend URL is not configured. Set API_BASE_URL in the server environment.",
  );
}

export async function backendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);

  // Keep the API key server-side.
  headers.set("X-API-Key", BACKEND_API_KEY);

  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}