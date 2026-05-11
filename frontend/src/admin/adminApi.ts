// REST client for /api/admin/*. All calls carry the X-Admin-Token header
// via adminFetch. Backend lives in streaming_admin.py.

import { adminFetch } from "./adminAuth";
import type { ConversationDetail } from "../api/conversations";

export interface ConnectionRow {
  ip: string;
  first_seen_at: string;
  last_seen_at: string;
  conversation_count: number;
  turns: number;
}

export interface ConnectionsResponse {
  count: number;
  ttl_days: number;
  rows: ConnectionRow[];
}

export interface ConversationRow {
  session_id: string;
  title: string;
  lang: "en" | "es";
  first_seen_at: string;
  last_seen_at: string;
  turn_count: number;
  deleted_at: string | null;
}

export interface ConversationsForIpResponse {
  ip: string;
  count: number;
  rows: ConversationRow[];
}

class AdminApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "AdminApiError";
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
  throw new AdminApiError(detail, res.status);
}

export async function listConnections(): Promise<ConnectionsResponse> {
  const res = await adminFetch("/api/admin/connections");
  if (!res.ok) await parseError(res, `list failed (${res.status})`);
  return (await res.json()) as ConnectionsResponse;
}

export async function conversationsForIp(
  ip: string,
): Promise<ConversationsForIpResponse> {
  const res = await adminFetch(
    `/api/admin/connections/${encodeURIComponent(ip)}/conversations`,
  );
  if (!res.ok) await parseError(res, `drill failed (${res.status})`);
  return (await res.json()) as ConversationsForIpResponse;
}

export async function getAdminConversation(
  sessionId: string,
): Promise<ConversationDetail> {
  const res = await adminFetch(
    `/api/admin/conversations/${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) await parseError(res, `get failed (${res.status})`);
  return (await res.json()) as ConversationDetail;
}

export { AdminApiError };
