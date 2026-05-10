// Small formatting helpers for the chat UI.

/** "3.2 s" / "320 ms" — used for tool durations and turn totals. */
export function formatDuration(ms: number | undefined): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return s < 10 ? `${s.toFixed(1)} s` : `${Math.round(s)} s`;
}

/** Truncate to N chars, appending an ellipsis when cut. */
export function truncate(text: string, max: number): string {
  if (!text) return "";
  if (text.length <= max) return text;
  // Cut on a word boundary if we find one within the last 12 chars.
  const slice = text.slice(0, max);
  const lastSpace = slice.lastIndexOf(" ");
  const cut = lastSpace > max - 12 ? lastSpace : max;
  return `${slice.slice(0, cut).trimEnd()}…`;
}

/** "Thought for 3.2 s · 2 tools" summary for the collapsed chip. */
export function summarizeReasoning(opts: {
  totalMs: number;
  toolCount: number;
  lang: "en" | "es";
}): string {
  const dur = formatDuration(opts.totalMs);
  if (opts.lang === "es") {
    if (opts.toolCount === 0) return `Pensó ${dur}`;
    return `Pensó ${dur} · ${opts.toolCount} ${opts.toolCount === 1 ? "herramienta" : "herramientas"}`;
  }
  if (opts.toolCount === 0) return `Thought for ${dur}`;
  return `Thought for ${dur} · ${opts.toolCount} tool${opts.toolCount === 1 ? "" : "s"}`;
}
