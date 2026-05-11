// Admin auth helpers. Parallel to lib/auth.ts but with a separate storage
// key and a separate header name so an admin can sign in to /admin without
// touching the evaluator token in /api/wiki-tutor's flow. The admin endpoint
// is reachable only via SSM port-forward (Caddy 404s the public path) so
// loading this page from https://lasalle.generateeve.com/admin will succeed
// at fetching the bundle but every API call will fail with 404 — that's
// the intended outcome.

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
 *   401 → token wrong (or unset on the box)
 *   404 → reached Caddy's edge filter — caller is on the public URL,
 *         not a loopback port-forward. Tell them where to go.
 *   other → network or server error
 */
export async function validateAdminToken(
  token: string,
): Promise<
  | { ok: true }
  | { ok: false; reason: "invalid" | "wrong_origin" | "network" }
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
  if (res.status === 404) return { ok: false, reason: "wrong_origin" };
  if (res.status === 401) return { ok: false, reason: "invalid" };
  return { ok: false, reason: "network" };
}
