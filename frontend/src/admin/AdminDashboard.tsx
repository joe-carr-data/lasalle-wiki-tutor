import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "../components/icons";
import { ReplayThread } from "../components/ReplayThread";
import { clearStoredAdminToken } from "./adminAuth";
import {
  conversationsForIp,
  getAdminConversation,
  listConnections,
  type ConnectionRow,
  type ConnectionsResponse,
  type ConversationRow,
  type ConversationsForIpResponse,
} from "./adminApi";
import type { ConversationDetail } from "../api/conversations";

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

interface DrillState {
  loading: boolean;
  data: ConversationsForIpResponse | null;
  error: string | null;
}

export function AdminDashboard() {
  const [roster, setRoster] = useState<ConnectionsResponse | null>(null);
  const [rosterLoading, setRosterLoading] = useState(true);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [expandedIp, setExpandedIp] = useState<string | null>(null);
  const [drill, setDrill] = useState<Record<string, DrillState>>({});

  // Right pane state
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ConversationDetail | null>(
    null,
  );
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const fetchRoster = useCallback(async () => {
    setRosterError(null);
    setRosterLoading(true);
    try {
      const data = await listConnections();
      setRoster(data);
    } catch (err) {
      setRosterError(err instanceof Error ? err.message : "failed to load roster");
    } finally {
      setRosterLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRoster();
  }, [fetchRoster]);

  const toggleIp = useCallback(
    async (ip: string) => {
      if (expandedIp === ip) {
        setExpandedIp(null);
        return;
      }
      setExpandedIp(ip);
      if (drill[ip]?.data) return;
      setDrill((d) => ({
        ...d,
        [ip]: { loading: true, data: null, error: null },
      }));
      try {
        const data = await conversationsForIp(ip);
        setDrill((d) => ({
          ...d,
          [ip]: { loading: false, data, error: null },
        }));
      } catch (err) {
        setDrill((d) => ({
          ...d,
          [ip]: {
            loading: false,
            data: null,
            error: err instanceof Error ? err.message : "failed to drill",
          },
        }));
      }
    },
    [drill, expandedIp],
  );

  const selectConversation = useCallback(async (row: ConversationRow) => {
    setSelectedSessionId(row.session_id);
    setSelectedDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const detail = await getAdminConversation(row.session_id);
      setSelectedDetail(detail);
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "failed to load conversation",
      );
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const totals = useMemo(() => {
    if (!roster) return { ips: 0, conversations: 0, turns: 0 };
    return roster.rows.reduce(
      (acc, row) => ({
        ips: acc.ips + 1,
        conversations: acc.conversations + row.conversation_count,
        turns: acc.turns + row.turns,
      }),
      { ips: 0, conversations: 0, turns: 0 },
    );
  }, [roster]);

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <div>
          <div className="admin-eyebrow">LaSalle Wiki Tutor</div>
          <h1 className="admin-title admin-title--inline">Operator dashboard</h1>
        </div>
        <div className="admin-header-actions">
          <button className="admin-btn admin-btn--ghost" onClick={fetchRoster}>
            Refresh
          </button>
          <button
            className="admin-btn admin-btn--ghost"
            onClick={() => clearStoredAdminToken()}
          >
            Sign out
          </button>
        </div>
      </header>

      <section className="admin-summary">
        <div className="admin-summary-card">
          <div className="admin-summary-value">{totals.ips}</div>
          <div className="admin-summary-label">distinct IPs</div>
        </div>
        <div className="admin-summary-card">
          <div className="admin-summary-value">{totals.conversations}</div>
          <div className="admin-summary-label">conversations</div>
        </div>
        <div className="admin-summary-card">
          <div className="admin-summary-value">{totals.turns}</div>
          <div className="admin-summary-label">turns</div>
        </div>
        <div className="admin-summary-card admin-summary-card--note">
          <div className="admin-summary-value">{roster?.ttl_days ?? 30}d</div>
          <div className="admin-summary-label">retention TTL</div>
        </div>
      </section>

      <div className="admin-split">
        <aside className="admin-pane admin-pane--list">
          <div className="admin-pane-title">Connections</div>
          {rosterError && (
            <div className="admin-error" role="alert">
              {rosterError}
            </div>
          )}
          {rosterLoading && !roster ? (
            <div className="admin-loading">
              <Loader2 className="ico-sm tl-spin" />
              <span>Loading roster…</span>
            </div>
          ) : roster && roster.rows.length === 0 ? (
            <div className="admin-empty">
              No IP records yet. They'll appear here after the next stream turn.
            </div>
          ) : roster ? (
            <ul className="admin-ip-list">
              {roster.rows.map((row) => (
                <IpCard
                  key={row.ip}
                  row={row}
                  expanded={expandedIp === row.ip}
                  onToggle={() => toggleIp(row.ip)}
                  drillState={drill[row.ip]}
                  selectedSessionId={selectedSessionId}
                  onSelectConversation={selectConversation}
                />
              ))}
            </ul>
          ) : null}
        </aside>

        <main className="admin-pane admin-pane--detail">
          {!selectedSessionId ? (
            <div className="admin-detail-empty">
              <div className="admin-detail-empty-mark">
                <span>↩</span>
              </div>
              <div className="admin-detail-empty-text">
                Pick a conversation on the left to read the full transcript,
                reasoning chain, and tool calls.
              </div>
            </div>
          ) : detailLoading ? (
            <div className="admin-loading">
              <Loader2 className="ico-md tl-spin" />
              <span>Loading conversation…</span>
            </div>
          ) : detailError ? (
            <div className="admin-error" role="alert">
              {detailError}
            </div>
          ) : selectedDetail ? (
            <ConversationView detail={selectedDetail} />
          ) : null}
        </main>
      </div>
    </div>
  );
}

interface IpCardProps {
  row: ConnectionRow;
  expanded: boolean;
  onToggle: () => void;
  drillState: DrillState | undefined;
  selectedSessionId: string | null;
  onSelectConversation: (row: ConversationRow) => void;
}

function IpCard({
  row,
  expanded,
  onToggle,
  drillState,
  selectedSessionId,
  onSelectConversation,
}: IpCardProps) {
  return (
    <li className={`admin-ip-card ${expanded ? "admin-ip-card--expanded" : ""}`}>
      <button
        type="button"
        className="admin-ip-summary"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="admin-ip-disclosure" aria-hidden="true">
          {expanded ? "▾" : "▸"}
        </span>
        <span className="admin-ip-addr">{row.ip}</span>
        <span className="admin-ip-meta">
          {row.conversation_count} conv · {row.turns} turns
        </span>
        <span className="admin-ip-time" title={formatTimestamp(row.last_seen_at)}>
          {formatRelative(row.last_seen_at)}
        </span>
      </button>
      {expanded && (
        <div className="admin-conv-list">
          {drillState?.loading ? (
            <div className="admin-loading admin-loading--inline">
              <Loader2 className="ico-sm tl-spin" />
              <span>Loading…</span>
            </div>
          ) : drillState?.error ? (
            <div className="admin-error">{drillState.error}</div>
          ) : drillState?.data && drillState.data.rows.length === 0 ? (
            <div className="admin-empty admin-empty--inline">No conversations.</div>
          ) : drillState?.data ? (
            <ul className="admin-conv-items">
              {drillState.data.rows.map((c) => (
                <li
                  key={c.session_id}
                  className={`admin-conv-item ${
                    selectedSessionId === c.session_id
                      ? "admin-conv-item--selected"
                      : ""
                  }`}
                >
                  <button
                    type="button"
                    className="admin-conv-btn"
                    onClick={() => onSelectConversation(c)}
                  >
                    <div className="admin-conv-title">
                      {c.title}
                      {c.deleted_at && (
                        <span className="admin-tag admin-tag--muted">deleted</span>
                      )}
                    </div>
                    <div className="admin-conv-meta">
                      <span className="admin-tag">{c.lang}</span>
                      <span>{c.turn_count} turns</span>
                      <span title={formatTimestamp(c.last_seen_at)}>
                        {formatRelative(c.last_seen_at)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </li>
  );
}

function ConversationView({ detail }: { detail: ConversationDetail }) {
  return (
    <div className="admin-conv-view">
      <header className="admin-conv-header">
        <div className="admin-conv-header-title">{detail.title}</div>
        <div className="admin-conv-header-meta">
          <span className="admin-tag">{detail.lang}</span>
          <span>{detail.turns.length} turns</span>
          <span className="admin-conv-id" title={detail.id}>
            {detail.id}
          </span>
        </div>
      </header>
      <div className="admin-conv-thread">
        <ReplayThread detail={detail} lang={detail.lang} />
      </div>
    </div>
  );
}
