// REST client for /api/wiki-tutor/v1/conversations. Plain fetch — no
// extra abstraction. Backend lives in streaming_conversations.py.

const BASE = "/api/wiki-tutor/v1/conversations";

export interface ConversationSummary {
  id: string;
  title: string;
  lang: "en" | "es";
  version: number;
  turn_count: number;
  updated_at: string | null;
}

export interface ConversationTurn {
  run_id: string;
  user: { text: string };
  agent: { text: string };
  reasoning: ReplayReasoningStep[];
  has_trace: boolean;
}

export type ReplayReasoningStep =
  | {
      kind: "thought";
      text: string;
      started_at?: number | null;
      ended_at?: number | null;
    }
  | {
      kind: "tool";
      name: string;
      args_display: string;
      duration_ms?: number | null;
      duration_display?: string | null;
      preview?: string | null;
      icon?: string | null;
    };

export interface ConversationDetail {
  id: string;
  title: string;
  lang: "en" | "es";
  version: number;
  created_at: string | null;
  updated_at: string | null;
  turns: ConversationTurn[];
}

class ConversationsApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ConversationsApiError";
    this.status = status;
  }
}

async function parseError(res: Response, fallback: string): Promise<never> {
  let detail: string;
  try {
    const body = (await res.json()) as { detail?: string };
    detail = body.detail || fallback;
  } catch {
    detail = fallback;
  }
  throw new ConversationsApiError(detail, res.status);
}

export async function listConversations(
  userId: string,
  signal?: AbortSignal,
): Promise<ConversationSummary[]> {
  const res = await fetch(`${BASE}?user_id=${encodeURIComponent(userId)}`, {
    signal,
  });
  if (!res.ok) await parseError(res, `list failed (${res.status})`);
  const body = (await res.json()) as { items: ConversationSummary[] };
  return body.items;
}

export async function getConversation(
  id: string,
  userId: string,
  signal?: AbortSignal,
): Promise<ConversationDetail> {
  const res = await fetch(
    `${BASE}/${encodeURIComponent(id)}?user_id=${encodeURIComponent(userId)}`,
    { signal },
  );
  if (!res.ok) await parseError(res, `get failed (${res.status})`);
  return (await res.json()) as ConversationDetail;
}

export async function renameConversation(
  id: string,
  title: string,
  expectedVersion: number,
): Promise<{ id: string; title: string; version: number; updated_at: string }> {
  const res = await fetch(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, expected_version: expectedVersion }),
  });
  if (!res.ok) await parseError(res, `rename failed (${res.status})`);
  return (await res.json()) as {
    id: string;
    title: string;
    version: number;
    updated_at: string;
  };
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    await parseError(res, `delete failed (${res.status})`);
  }
}

export { ConversationsApiError };
