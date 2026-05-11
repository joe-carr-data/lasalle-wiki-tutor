// Admin auth helpers. Parallel to lib/auth.ts but with a separate storage
// key and a separate header name so the admin session is fully independent
// of the evaluator session. The admin token is the only gate on
// /api/admin/* — per-IP rate limiting (server-side) is the second layer
// that bounds brute-force probing.

const STORAGE_KEY = "wiki-tutor.admin-token";
const HEADER = "X-Admin-Token";

type Listener = () => void;
const listeners = new Set<Listener>();

export function getStoredAdminToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredAdminToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* localStorage unavailable */
  }
}

export function clearStoredAdminToken(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  for (const l of listeners) l();
}

export function onAdminTokenCleared(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** `fetch` wrapper that injects the stored admin token. */
export async function adminFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const token = getStoredAdminToken();
  const headers = new Headers(init.headers);
  if (token) headers.set(HEADER, token);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    clearStoredAdminToken();
  }
  return res;
}

/**
 * Validate an admin token by attempting the cheapest admin call. The
 * endpoint itself does the work (constant-time compare server-side); we
 * just classify the response:
 *
 *   200 → valid
 *   401 → token wrong
 *   429 → rate-limited
 *   503 → server has no token configured (env var unset)
 *   other → network or server error
 */
export async function validateAdminToken(
  token: string,
): Promise<
  | { ok: true }
  | { ok: false; reason: "invalid" | "rate_limited" | "unconfigured" | "network"; retryAfter?: number }
> {
  let res: Response;
  try {
    res = await fetch("/api/admin/connections?limit=1", {
      headers: { "X-Admin-Token": token },
    });
  } catch {
    return { ok: false, reason: "network" };
  }
  if (res.status === 200) return { ok: true };
  if (res.status === 401) return { ok: false, reason: "invalid" };
  if (res.status === 429) {
    const retryAfter = Number(res.headers.get("Retry-After")) || 60;
    return { ok: false, reason: "rate_limited", retryAfter };
  }
  if (res.status === 503) return { ok: false, reason: "unconfigured" };
  return { ok: false, reason: "network" };
}
