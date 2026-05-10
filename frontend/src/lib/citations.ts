// Extract a deduped list of salleurl.edu citation links from the agent's
// markdown answer. The agent system prompt requires it to cite source URLs
// inline as markdown links — we surface them as a "Sources" footer too.

export interface CitationRef {
  href: string;
  label: string;
}

const LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
const BARE_URL_RE = /(?<!\()https?:\/\/(?:www\.)?salleurl\.edu\/[^\s)]+/g;

function isSalleUrl(href: string): boolean {
  try {
    const u = new URL(href);
    return u.hostname.endsWith("salleurl.edu");
  } catch {
    return false;
  }
}

/** Trim trailing punctuation that markdown picks up as part of the URL. */
function stripTrailingPunct(href: string): string {
  return href.replace(/[.,;:!?)\]]+$/g, "");
}

/** Pull a short, human-readable label from a salleurl.edu path. */
function labelFromUrl(href: string): string {
  try {
    const u = new URL(href);
    const segments = u.pathname.split("/").filter(Boolean);
    const last = segments[segments.length - 1] ?? u.hostname;
    return decodeURIComponent(last).replace(/[-_]+/g, " ").trim() || u.hostname;
  } catch {
    return href;
  }
}

export function extractCitations(markdown: string): CitationRef[] {
  if (!markdown) return [];
  const seen = new Map<string, CitationRef>();

  for (const match of markdown.matchAll(LINK_RE)) {
    const [, rawLabel, rawHref] = match;
    const href = stripTrailingPunct(rawHref);
    if (!isSalleUrl(href)) continue;
    if (seen.has(href)) continue;
    const label = rawLabel?.trim() || labelFromUrl(href);
    seen.set(href, { href, label });
  }

  for (const match of markdown.matchAll(BARE_URL_RE)) {
    const href = stripTrailingPunct(match[0]);
    if (!isSalleUrl(href)) continue;
    if (seen.has(href)) continue;
    seen.set(href, { href, label: labelFromUrl(href) });
  }

  return Array.from(seen.values());
}
