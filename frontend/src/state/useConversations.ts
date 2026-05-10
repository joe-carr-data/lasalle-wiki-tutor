import { useCallback, useEffect, useRef, useState } from "react";
import {
  ConversationsApiError,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  type ConversationDetail,
  type ConversationSummary,
} from "../api/conversations";

interface UseConversationsState {
  items: ConversationSummary[];
  activeId: string | null;
  detail: ConversationDetail | null;
  loadingList: boolean;
  loadingDetail: boolean;
  error: string | null;
}

export interface UseConversations extends UseConversationsState {
  refresh: () => Promise<void>;
  select: (id: string | null) => Promise<void>;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  /** Optimistically bump a conversation to the top after a turn completes. */
  bumpToTop: (id: string, title?: string) => void;
  /** Handle a brand-new session id created in-memory (pre-first-turn). */
  setActive: (id: string) => void;
}

const EMPTY_STATE: UseConversationsState = {
  items: [],
  activeId: null,
  detail: null,
  loadingList: false,
  loadingDetail: false,
  error: null,
};

export function useConversations(userId: string): UseConversations {
  const [state, setState] = useState<UseConversationsState>(EMPTY_STATE);

  // Race-safety: each select() bumps a sequence counter. Slow GETs that
  // return after the user clicked elsewhere are dropped.
  const seqRef = useRef(0);
  const detailAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loadingList: true, error: null }));
    try {
      const items = await listConversations(userId);
      setState((s) => ({ ...s, items, loadingList: false }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "list failed";
      setState((s) => ({ ...s, loadingList: false, error: msg }));
    }
  }, [userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const select = useCallback(
    async (id: string | null) => {
      detailAbortRef.current?.abort();
      const seq = ++seqRef.current;

      if (!id) {
        setState((s) => ({ ...s, activeId: null, detail: null }));
        return;
      }

      const ctrl = new AbortController();
      detailAbortRef.current = ctrl;
      setState((s) => ({
        ...s,
        activeId: id,
        loadingDetail: true,
        error: null,
      }));

      try {
        const detail = await getConversation(id, userId, ctrl.signal);
        if (seq !== seqRef.current) return; // user moved on
        setState((s) => ({ ...s, detail, loadingDetail: false }));
      } catch (err) {
        if (ctrl.signal.aborted) return;
        if (seq !== seqRef.current) return;
        const msg =
          err instanceof ConversationsApiError && err.status === 404
            ? "conversation not found"
            : err instanceof Error
              ? err.message
              : "load failed";
        setState((s) => ({ ...s, loadingDetail: false, error: msg }));
      }
    },
    [userId],
  );

  const rename = useCallback(
    async (id: string, title: string) => {
      const cleaned = title.trim();
      if (!cleaned) return;
      const before = state.items;
      const target = before.find((c) => c.id === id);
      // Optimistic update: write the new title locally; rollback on failure.
      setState((s) => ({
        ...s,
        items: s.items.map((c) => (c.id === id ? { ...c, title: cleaned } : c)),
        detail:
          s.detail && s.detail.id === id ? { ...s.detail, title: cleaned } : s.detail,
      }));
      try {
        const result = await renameConversation(id, cleaned, target?.version ?? 1);
        setState((s) => ({
          ...s,
          items: s.items.map((c) =>
            c.id === id
              ? { ...c, title: result.title, version: result.version }
              : c,
          ),
          detail:
            s.detail && s.detail.id === id
              ? { ...s.detail, title: result.title, version: result.version }
              : s.detail,
        }));
      } catch (err) {
        // Rollback + surface error.
        setState((s) => ({ ...s, items: before }));
        const msg = err instanceof Error ? err.message : "rename failed";
        setState((s) => ({ ...s, error: msg }));
        // If a 409 hits, our cached version is stale — refetch the list.
        if (err instanceof ConversationsApiError && err.status === 409) {
          void refresh();
        }
      }
    },
    [refresh, state.items],
  );

  const remove = useCallback(
    async (id: string) => {
      const before = state.items;
      setState((s) => ({
        ...s,
        items: s.items.filter((c) => c.id !== id),
        activeId: s.activeId === id ? null : s.activeId,
        detail: s.detail && s.detail.id === id ? null : s.detail,
      }));
      try {
        await deleteConversation(id);
      } catch (err) {
        // Rollback on failure.
        setState((s) => ({ ...s, items: before }));
        const msg = err instanceof Error ? err.message : "delete failed";
        setState((s) => ({ ...s, error: msg }));
      }
    },
    [state.items],
  );

  const bumpToTop = useCallback((id: string, title?: string) => {
    setState((s) => {
      const idx = s.items.findIndex((c) => c.id === id);
      const now = new Date().toISOString();
      if (idx === -1) {
        // First turn of a new conversation — backend just inserted it; we
        // refresh in the background to pull the heuristic title.
        return s;
      }
      const updated = {
        ...s.items[idx],
        ...(title ? { title } : {}),
        updated_at: now,
        turn_count: s.items[idx].turn_count + 1,
      };
      const rest = s.items.filter((_, i) => i !== idx);
      return { ...s, items: [updated, ...rest] };
    });
  }, []);

  const setActive = useCallback((id: string) => {
    setState((s) => (s.activeId === id ? s : { ...s, activeId: id }));
  }, []);

  return {
    ...state,
    refresh,
    select,
    rename,
    remove,
    bumpToTop,
    setActive,
  };
}
