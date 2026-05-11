import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2 } from "../components/icons";
import {
  adminFetch,
  clearStoredAdminToken,
} from "./adminAuth";

interface ConnectionRow {
  ip: string;
  first_seen_at: string;
  last_seen_at: string;
  conversation_count: number;
  turns: number;
}

interface ConnectionsResponse {
  count: number;
  ttl_days: number;
  rows: ConnectionRow[];
}

interface ConversationRow {
  session_id: string;
  title: string;
  lang: string;
  first_seen_at: string;
  last_seen_at: string;
  turn_count: number;
  deleted_at: string | null;
}

interface ConversationsResponse {
  ip: string;
  count: number;
  rows: ConversationRow[];
}

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

export function AdminDashboard() {
  const [data, setData] = useState<ConnectionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIp, setExpandedIp] = useState<string | null>(null);
  const [drill, setDrill] = useState<
    Record<string, { loading: boolean; rows: ConversationRow[]; error: string | null }>
  >({});

  const fetchRoster = useCallback(async () => {
    setError(null);
    try {
      const res = await adminFetch("/api/admin/connections");
      if (!res.ok) {
        setError(`server returned ${res.status}`);
        setData(null);
        return;
      }
      const body = (await res.json()) as ConnectionsResponse;
      setData(body);
    } catch {
      setError("network error fetching roster");
    } finally {
      setLoading(false);
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
      if (drill[ip]) return;
      setDrill((d) => ({ ...d, [ip]: { loading: true, rows: [], error: null } }));
      try {
        const res = await adminFetch(
          `/api/admin/connections/${encodeURIComponent(ip)}/conversations`,
        );
        if (!res.ok) {
          setDrill((d) => ({
            ...d,
            [ip]: { loading: false, rows: [], error: `server returned ${res.status}` },
          }));
          return;
        }
        const body = (await res.json()) as ConversationsResponse;
        setDrill((d) => ({
          ...d,
          [ip]: { loading: false, rows: body.rows, error: null },
        }));
      } catch {
        setDrill((d) => ({
          ...d,
          [ip]: { loading: false, rows: [], error: "network error" },
        }));
      }
    },
    [drill, expandedIp],
  );

  const totals = useMemo(() => {
    if (!data) return { ips: 0, conversations: 0, turns: 0 };
    return data.rows.reduce(
      (acc, row) => ({
        ips: acc.ips + 1,
        conversations: acc.conversations + row.conversation_count,
        turns: acc.turns + row.turns,
      }),
      { ips: 0, conversations: 0, turns: 0 },
    );
  }, [data]);

  return (
    <div className="admin-stage admin-stage--dashboard">
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
          <div className="admin-summary-value">{data?.ttl_days ?? 30}d</div>
          <div className="admin-summary-label">retention TTL</div>
        </div>
      </section>

      {error && (
        <div className="admin-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className="admin-loading">
          <Loader2 className="ico-md tl-spin" />
          <span>Loading roster…</span>
        </div>
      ) : data && data.rows.length === 0 ? (
        <div className="admin-empty">
          No IP records yet. They'll appear here after the next stream turn.
        </div>
      ) : data ? (
        <table className="admin-table">
          <thead>
            <tr>
              <th>IP</th>
              <th>Conversations</th>
              <th>Turns</th>
              <th>First seen</th>
              <th>Last activity</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <FragmentRow
                key={row.ip}
                row={row}
                expanded={expandedIp === row.ip}
                onToggle={() => toggleIp(row.ip)}
                drillState={drill[row.ip]}
              />
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

interface FragmentRowProps {
  row: ConnectionRow;
  expanded: boolean;
  onToggle: () => void;
  drillState:
    | { loading: boolean; rows: ConversationRow[]; error: string | null }
    | undefined;
}

function FragmentRow({ row, expanded, onToggle, drillState }: FragmentRowProps) {
  return (
    <>
      <tr
        className={`admin-row ${expanded ? "admin-row--expanded" : ""}`}
        onClick={onToggle}
      >
        <td className="admin-cell-mono">{row.ip}</td>
        <td>{row.conversation_count}</td>
        <td>{row.turns}</td>
        <td title={formatTimestamp(row.first_seen_at)}>
          {formatRelative(row.first_seen_at)}
        </td>
        <td title={formatTimestamp(row.last_seen_at)}>
          {formatRelative(row.last_seen_at)}
        </td>
      </tr>
      {expanded && (
        <tr className="admin-drill-row">
          <td colSpan={5}>
            {drillState?.loading ? (
              <div className="admin-loading">
                <Loader2 className="ico-sm tl-spin" />
                <span>Loading conversations…</span>
              </div>
            ) : drillState?.error ? (
              <div className="admin-error">{drillState.error}</div>
            ) : drillState && drillState.rows.length === 0 ? (
              <div className="admin-empty">No conversations recorded yet.</div>
            ) : drillState ? (
              <table className="admin-table admin-table--inner">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Lang</th>
                    <th>Turns</th>
                    <th>First seen</th>
                    <th>Last activity</th>
                    <th>Deleted</th>
                  </tr>
                </thead>
                <tbody>
                  {drillState.rows.map((c) => (
                    <tr key={c.session_id}>
                      <td>
                        <div className="admin-title-cell">{c.title}</div>
                        <div className="admin-session-id">{c.session_id}</div>
                      </td>
                      <td>{c.lang}</td>
                      <td>{c.turn_count}</td>
                      <td title={formatTimestamp(c.first_seen_at)}>
                        {formatRelative(c.first_seen_at)}
                      </td>
                      <td title={formatTimestamp(c.last_seen_at)}>
                        {formatRelative(c.last_seen_at)}
                      </td>
                      <td>{c.deleted_at ? "yes" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </td>
        </tr>
      )}
    </>
  );
}
