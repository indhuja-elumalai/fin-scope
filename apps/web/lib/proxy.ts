// Server-only wrapper around backendFetch for the app/api/* route handlers.
//
// Same signature and same request as lib/backend.ts. It only changes what
// happens when things go wrong, so the browser always receives JSON:
//   - the backend is unreachable (cold start, network error): a 502 with
//     {"detail": "..."} instead of an unhandled exception and an HTML page;
//   - the backend answers with a non-JSON body (e.g. a plain-text 500): the
//     same status, with the text wrapped as {"detail": "..."}.
// Successful JSON responses pass through unchanged.
import { backendFetch as rawBackendFetch } from "@/lib/backend";

const NO_BODY_STATUSES = new Set([204, 205, 304]);

function jsonError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await rawBackendFetch(path, init);
  } catch {
    return jsonError(
      502,
      "The FIN-SCOPE API could not be reached. If it is on a free tier it may be waking up; try again in a minute.",
    );
  }

  if (NO_BODY_STATUSES.has(response.status)) return response;

  const text = await response.text();
  try {
    JSON.parse(text);
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return jsonError(
      response.status >= 400 ? response.status : 502,
      text.trim() || `The FIN-SCOPE API returned an empty response (HTTP ${response.status}).`,
    );
  }
}
