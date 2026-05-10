// Demo-grade access gate. The token lives in localStorage; every API call
// goes through `authedFetch` which injects it as `X-Access-Token`. On any
// 401 from the server we wipe the stored token and notify subscribers so
// the Gate screen re-mounts.
//
// There is no real identity here — it's a single shared secret distributed
// to the university evaluators. The per-browser `userId` (lib/userId.ts) is
// orthogonal: it scopes each evaluator's conversation list, but does not
// authenticate them.

const STORAGE_KEY = "wiki-tutor.access-token";
const HEADER = "X-Access-Token";

type Listener = () => void;
const listeners = new Set<Listener>();

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* localStorage unavailable — nothing we can do */
  }
}

export function clearStoredToken(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  for (const l of listeners) l();
}

/** Subscribe to token-cleared events (the only signal the Gate needs). */
export function onTokenCleared(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * `fetch` wrapper that injects the stored access token. On 401 from the
 * backend we drop the token and broadcast — the Gate re-mounts and the
 * pending caller still receives the 401 so it can stop its work.
 *
 * SSE callers pass `init.body` and a `signal`; this wrapper preserves both
 * unmodified. Headers are merged: caller's `Content-Type` / `Accept` win.
 */
export async function authedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  if (token) headers.set(HEADER, token);

  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    // The token went stale (rotated server-side, or never was valid).
    clearStoredToken();
  }
  return res;
}

/**
 * Validate a token against the backend. Returns:
 *   - { ok: true } on success — caller stores the token.
 *   - { ok: false, reason: "invalid" | "rate_limited" | "network" } otherwise.
 */
export async function validateToken(
  token: string,
): Promise<
  | { ok: true }
  | { ok: false; reason: "invalid" | "rate_limited" | "network"; retryAfter?: number }
> {
  let res: Response;
  try {
    res = await fetch("/api/auth/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
  } catch {
    return { ok: false, reason: "network" };
  }

  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After")) || 60;
    return { ok: false, reason: "rate_limited", retryAfter };
  }
  if (!res.ok) {
    return { ok: false, reason: "invalid" };
  }
  try {
    const body = (await res.json()) as { valid?: boolean };
    return body.valid ? { ok: true } : { ok: false, reason: "invalid" };
  } catch {
    return { ok: false, reason: "network" };
  }
}
