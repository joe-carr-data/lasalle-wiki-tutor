import { useCallback, useReducer, useRef } from "react";
import { streamQuery, StreamError } from "../api/stream";
import type { SseEvent, StreamRequestBody } from "../api/types";

// ─── Domain model ─────────────────────────────────────────────────────────

export type ReasoningStep =
  | {
      kind: "thought";
      id: string;
      text: string;
      status: "active" | "done";
      startedAt: number;
      endedAt?: number;
    }
  | {
      kind: "tool";
      id: string; // call_id from the server
      name: string;
      icon: string;
      argsDisplay: string;
      startedAt: number;
      endedAt?: number;
      durationMs?: number;
      durationDisplay?: string;
      preview?: string;
      status: "active" | "done" | "error";
    };

export type TurnStatus = "streaming" | "done" | "cancelled" | "error";

export interface Turn {
  id: string; // query_id
  user: { text: string; lang: "en" | "es" };
  reasoning: ReasoningStep[];
  answer: { markdown: string; done: boolean };
  status: TurnStatus;
  error?: string;
  startedAt: number;
  finishedAt?: number;
  totalDurationDisplay?: string;
  responseOrigin?: string;
  conversationId?: string;
}

export interface ChatStreamState {
  sessionId: string | null;
  turns: Turn[];
  isStreaming: boolean;
}

// ─── Reducer ──────────────────────────────────────────────────────────────

type Action =
  | { type: "session/start"; sessionId: string }
  | { type: "turn/start"; turn: Turn }
  | { type: "sse"; turnId: string; event: SseEvent }
  | { type: "turn/error"; turnId: string; message: string }
  | { type: "turn/cancelled"; turnId: string };

const initialState: ChatStreamState = {
  sessionId: null,
  turns: [],
  isStreaming: false,
};

function updateTurn(
  state: ChatStreamState,
  turnId: string,
  patch: (t: Turn) => Turn,
): ChatStreamState {
  let changed = false;
  const turns = state.turns.map((t) => {
    if (t.id !== turnId) return t;
    changed = true;
    return patch(t);
  });
  return changed ? { ...state, turns } : state;
}

function findActiveThoughtIndex(reasoning: ReasoningStep[]): number {
  for (let i = reasoning.length - 1; i >= 0; i--) {
    const step = reasoning[i];
    if (step.kind === "thought" && step.status === "active") return i;
  }
  return -1;
}

function reducer(state: ChatStreamState, action: Action): ChatStreamState {
  switch (action.type) {
    case "session/start":
      return { ...state, sessionId: action.sessionId };

    case "turn/start":
      return {
        ...state,
        turns: [...state.turns, action.turn],
        isStreaming: true,
      };

    case "turn/error":
      return {
        ...updateTurn(state, action.turnId, (t) => ({
          ...t,
          status: "error",
          error: action.message,
          finishedAt: Date.now(),
        })),
        isStreaming: false,
      };

    case "turn/cancelled":
      return {
        ...updateTurn(state, action.turnId, (t) =>
          t.status === "streaming"
            ? { ...t, status: "cancelled", finishedAt: Date.now() }
            : t,
        ),
        isStreaming: false,
      };

    case "sse":
      return applySseEvent(state, action.turnId, action.event);

    default:
      return state;
  }
}

function applySseEvent(
  state: ChatStreamState,
  turnId: string,
  ev: SseEvent,
): ChatStreamState {
  // Belt-and-braces: any reducer error gets logged + swallowed instead of
  // unmounting the whole chat. Treat all event payload fields as optional;
  // only `final_response.end` is guaranteed to carry the full answer.
  try {
    return _applySseEvent(state, turnId, ev);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("SSE reducer error on event", ev.event, err);
    return state;
  }
}

function _applySseEvent(
  state: ChatStreamState,
  turnId: string,
  ev: SseEvent,
): ChatStreamState {
  // Per-event payloads are accessed below via ev.data.X — every individual
  // field is treated as optional and string-coerced before any concat.
  // The outer try/catch in applySseEvent still catches the rare case of
  // ev.data itself being undefined.
  switch (ev.event) {
    case "session.started":
      // Lock in the server-assigned session id if it differs (resumed session).
      return ev.data.session_id && ev.data.session_id !== state.sessionId
        ? { ...state, sessionId: ev.data.session_id }
        : state;

    case "agent.thinking.start":
      return updateTurn(state, turnId, (t) => ({
        ...t,
        reasoning: [
          ...t.reasoning,
          {
            kind: "thought",
            id: ev.data.thinking_id || `thought-${t.reasoning.length}`,
            text: "",
            status: "active",
            startedAt: Date.now(),
          },
        ],
      }));

    case "agent.thinking.delta": {
      return updateTurn(state, turnId, (t) => {
        const reasoning = t.reasoning.slice();
        let idx = findActiveThoughtIndex(reasoning);
        if (idx === -1) {
          // Defensive: server skipped the start event — synthesize one.
          reasoning.push({
            kind: "thought",
            id: ev.data.thinking_id || `thought-${reasoning.length}`,
            text: "",
            status: "active",
            startedAt: Date.now(),
          });
          idx = reasoning.length - 1;
        }
        const cur = reasoning[idx] as Extract<ReasoningStep, { kind: "thought" }>;
        // Coerce both fields to string before any concat so a payload that
        // omits one of them cannot leak the literal "undefined" into the UI.
        const delta = typeof ev.data.delta === "string" ? ev.data.delta : "";
        const accumulated =
          typeof ev.data.accumulated === "string" ? ev.data.accumulated : null;
        const text = accumulated ?? cur.text + delta;
        reasoning[idx] = { ...cur, text };
        return { ...t, reasoning };
      });
    }

    case "agent.thinking.end":
      return updateTurn(state, turnId, (t) => {
        const reasoning = t.reasoning.slice();
        const idx = findActiveThoughtIndex(reasoning);
        if (idx === -1) return t;
        const cur = reasoning[idx] as Extract<ReasoningStep, { kind: "thought" }>;
        const finalText =
          typeof ev.data.full_text === "string" ? ev.data.full_text : cur.text;
        reasoning[idx] = { ...cur, text: finalText, status: "done", endedAt: Date.now() };
        return { ...t, reasoning };
      });

    case "tool.start": {
      // The contract says data.tool is always present, but defending
      // against a missing field is cheaper than diagnosing a render
      // crash that blanks the chat.
      const tool = ev.data.tool ?? ({} as Partial<typeof ev.data.tool>);
      return updateTurn(state, turnId, (t) => ({
        ...t,
        reasoning: [
          ...t.reasoning,
          {
            kind: "tool",
            id:
              (typeof tool.call_id === "string" && tool.call_id) ||
              `tool-${t.reasoning.length}`,
            name: tool.name || "tool",
            icon: tool.icon || "",
            argsDisplay: tool.arguments_display || "",
            startedAt: Date.now(),
            status: "active",
          },
        ],
      }));
    }

    case "tool.end": {
      const tool = ev.data.tool ?? ({} as Partial<typeof ev.data.tool>);
      const callId = typeof tool.call_id === "string" ? tool.call_id : "";
      const name = tool.name || "";
      return updateTurn(state, turnId, (t) => {
        const reasoning = t.reasoning.slice();
        // Match by call_id; fall back to FIFO by name (mirrors backend matching).
        let idx = -1;
        if (callId) {
          idx = reasoning.findIndex(
            (s) => s.kind === "tool" && s.status === "active" && s.id === callId,
          );
        }
        if (idx === -1 && name) {
          idx = reasoning.findIndex(
            (s) => s.kind === "tool" && s.status === "active" && s.name === name,
          );
        }
        if (idx === -1) {
          // Last resort: close the oldest still-active tool.
          idx = reasoning.findIndex(
            (s) => s.kind === "tool" && s.status === "active",
          );
        }
        if (idx === -1) return t;
        const cur = reasoning[idx] as Extract<ReasoningStep, { kind: "tool" }>;
        reasoning[idx] = {
          ...cur,
          status: ev.data.success === false ? "error" : "done",
          endedAt: Date.now(),
          durationMs: ev.data.duration_ms,
          durationDisplay: ev.data.duration_display,
          preview: ev.data.result_preview,
        };
        return { ...t, reasoning };
      });
    }

    case "final_response.delta":
      return updateTurn(state, turnId, (t) => {
        // Prefer the rolling accumulated text; if the server omitted it,
        // append the delta to the current markdown. Either way, never let
        // a missing field corrupt the answer with an "undefined" string.
        const accumulated =
          typeof ev.data.accumulated === "string" ? ev.data.accumulated : null;
        const delta = typeof ev.data.delta === "string" ? ev.data.delta : "";
        return {
          ...t,
          answer: {
            markdown: accumulated ?? t.answer.markdown + delta,
            done: false,
          },
        };
      });

    case "final_response.end":
      return updateTurn(state, turnId, (t) => ({
        ...t,
        answer: { markdown: ev.data.full_text || t.answer.markdown, done: true },
      }));

    case "response.final":
      return updateTurn(state, turnId, (t) => ({
        ...t,
        conversationId: ev.data.conversation_id,
        responseOrigin: ev.data.response_origin,
      }));

    case "session.ended":
      return {
        ...updateTurn(state, turnId, (t) =>
          t.status === "streaming"
            ? {
                ...t,
                status: "done",
                finishedAt: Date.now(),
                totalDurationDisplay: ev.data.total_duration_display,
              }
            : t,
        ),
        isStreaming: false,
      };

    case "cancelled":
      return {
        ...updateTurn(state, turnId, (t) =>
          t.status === "streaming"
            ? { ...t, status: "cancelled", finishedAt: Date.now() }
            : t,
        ),
        isStreaming: false,
      };

    case "error":
      return {
        ...updateTurn(state, turnId, (t) => ({
          ...t,
          status: "error",
          error: ev.data.message,
          finishedAt: Date.now(),
        })),
        isStreaming: false,
      };

    default:
      return state;
  }
}

// ─── Hook surface ─────────────────────────────────────────────────────────

export interface SendOptions {
  text: string;
  lang?: "en" | "es";
  reasoningEffort?: "low" | "medium" | "high";
  userId?: string;
}

export interface UseChatStream {
  state: ChatStreamState;
  send: (opts: SendOptions) => Promise<void>;
  cancel: () => void;
  retry: (turnId: string) => Promise<void>;
  resetSession: (sessionId: string) => void;
  hydrate: (sessionId: string, turns: Turn[]) => void;
}

function newId(prefix: string): string {
  // Browser-grade UUID; falls back for older runtimes.
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) return `${prefix}-${c.randomUUID()}`;
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useChatStream(initialSessionId?: string): UseChatStream {
  const [state, dispatch] = useReducer(
    reducer,
    initialSessionId ? { ...initialState, sessionId: initialSessionId } : initialState,
  );

  // Refs hold mutable streaming state (abort + the currently-in-flight body)
  // so re-renders don't recreate them and useCallback identities stay stable.
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | null>(initialSessionId ?? null);
  const lastSendRef = useRef<{ body: StreamRequestBody; turn: Turn } | null>(null);
  const activeQueryIdRef = useRef<string | null>(null);

  // Keep sessionIdRef in sync with the reducer's view.
  if (state.sessionId !== sessionIdRef.current) {
    sessionIdRef.current = state.sessionId;
  }

  const runStream = useCallback(async (body: StreamRequestBody, turn: Turn) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    lastSendRef.current = { body, turn };
    activeQueryIdRef.current = body.query_id;

    let firstDeltaSeen = false;
    try {
      for await (const ev of streamQuery(body, ctrl.signal)) {
        if (ev.event === "final_response.delta") firstDeltaSeen = true;
        dispatch({ type: "sse", turnId: turn.id, event: ev });
      }
    } catch (err) {
      if (ctrl.signal.aborted) {
        dispatch({ type: "turn/cancelled", turnId: turn.id });
        return;
      }
      const msg =
        err instanceof StreamError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Stream failed";
      // If we never saw the first answer delta and the failure is transient,
      // a retry button (UI-level) is the right path. We surface it as an
      // error event regardless — the UI shows a retry affordance for errored
      // turns. Auto-reconnect is intentionally NOT done here.
      void firstDeltaSeen;
      dispatch({ type: "turn/error", turnId: turn.id, message: msg });
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      if (activeQueryIdRef.current === body.query_id) activeQueryIdRef.current = null;
    }
  }, []);

  const send = useCallback(
    async ({ text, lang = "en", reasoningEffort = "medium", userId }: SendOptions) => {
      const sessionId = sessionIdRef.current ?? newId("sess");
      sessionIdRef.current = sessionId;
      dispatch({ type: "session/start", sessionId });

      const queryId = newId("q");
      const turn: Turn = {
        id: queryId,
        user: { text, lang },
        reasoning: [],
        answer: { markdown: "", done: false },
        status: "streaming",
        startedAt: Date.now(),
      };
      dispatch({ type: "turn/start", turn });

      const body: StreamRequestBody = {
        query: text,
        session_id: sessionId,
        query_id: queryId,
        user_id: userId,
        lang,
        reasoning_effort: reasoningEffort,
      };
      await runStream(body, turn);
    },
    [runStream],
  );

  const cancel = useCallback(() => {
    const queryId = activeQueryIdRef.current;
    abortRef.current?.abort();
    if (queryId) {
      // Fire-and-forget — the SSE generator will yield `cancelled` once the
      // server picks it up. We don't await; if the network is gone, the
      // local AbortController already terminated the read so the UI advances.
      void fetch("/api/wiki-tutor/v1/query/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query_id: queryId }),
      }).catch(() => {
        /* network failure during cancel is non-fatal — UI already aborted */
      });
    }
  }, []);

  const retry = useCallback(
    async (turnId: string) => {
      const last = lastSendRef.current;
      if (!last) return;
      // Only retry the most-recent turn — older turns are immutable.
      if (last.turn.id !== turnId) return;
      const queryId = newId("q");
      const turn: Turn = {
        ...last.turn,
        id: queryId,
        reasoning: [],
        answer: { markdown: "", done: false },
        status: "streaming",
        startedAt: Date.now(),
        finishedAt: undefined,
        error: undefined,
      };
      dispatch({ type: "turn/start", turn });
      const body: StreamRequestBody = { ...last.body, query_id: queryId };
      await runStream(body, turn);
    },
    [runStream],
  );

  const resetSession = useCallback((sessionId: string) => {
    abortRef.current?.abort();
    sessionIdRef.current = sessionId;
    lastSendRef.current = null;
    dispatch({ type: "session/start", sessionId });
  }, []);

  const hydrate = useCallback((sessionId: string, _turns: Turn[]) => {
    // Replay-time hydration: caller hands us a saved transcript. We accept
    // the session id; turns themselves are owned by useConversations and
    // rendered separately so stream state stays clean.
    abortRef.current?.abort();
    sessionIdRef.current = sessionId;
    lastSendRef.current = null;
    dispatch({ type: "session/start", sessionId });
  }, []);

  return { state, send, cancel, retry, resetSession, hydrate };
}
