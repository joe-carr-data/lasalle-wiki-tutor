// Stable per-browser user identifier — kept in localStorage. The demo has
// no real auth; in production this would be replaced with a server-issued
// id tied to a session cookie. Until then, this UUID is the only thing
// scoping the sidebar to "your" conversations.

const STORAGE_KEY = "wiki-tutor.user-id";

function generate(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `u-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function getUserId(): string {
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const fresh = generate();
    window.localStorage.setItem(STORAGE_KEY, fresh);
    return fresh;
  } catch {
    // Private mode / disabled storage — fall back to an in-memory id so
    // the conversation list still functions for the lifetime of the tab.
    return generate();
  }
}
