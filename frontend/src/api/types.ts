// SSE event union — mirrors fastapi_sse_contract.py + core/base_sse_adapter.py.
//
// We only model the subset the wiki-tutor UI consumes. Other team-mode events
// (delegation.*, graph.display, classification.*) are received but ignored
// upstream by the adapter for this single-agent product.

export type AgentRole = "router" | "specialist" | "underwriting" | "wiki_tutor" | string;

export interface AgentInfo {
  role: AgentRole;
  name: string;
  icon: string;
  color?: string;
}

interface BaseEnvelope<T extends string, D> {
  event: T;
  data: D & {
    // The server places these on the envelope, but reducers don't generally
    // need them. Kept here so consumers can read them when useful.
    event_id?: string;
    event_type?: T;
    timestamp?: string;
    elapsed_ms?: number;
    correlation_id?: string | null;
    agent?: AgentInfo;
  };
}

export interface SessionStartedData {
  query: string;
  session_id: string;
  question_answer_id: string;
  verbosity?: number;
}

export interface SessionEndedData {
  query: string;
  session_id: string;
  question_answer_id: string;
  total_duration_ms: number;
  total_duration_display: string;
  summary?: {
    agents_used?: string[];
    tools_executed?: number;
    delegations?: number;
  };
}

export interface ThinkingStartData {
  thinking_id: string;
}

export interface ThinkingDeltaData {
  thinking_id: string;
  delta: string;
  accumulated?: string;
}

export interface ThinkingEndData {
  thinking_id: string;
  duration_ms?: number;
  duration_display?: string;
  full_text?: string;
}

export interface ToolDescriptor {
  name: string;
  call_id: string;
  icon: string;
  arguments?: Record<string, unknown>;
  arguments_display: string;
}

export interface ToolStartData {
  tool: ToolDescriptor;
}

export interface ToolEndData {
  tool: ToolDescriptor;
  duration_ms: number;
  duration_display: string;
  result_preview?: string;
  success: boolean;
  orphaned?: boolean;
}

export interface FinalResponseStartData {
  /* server sends {} — agent info lives on the envelope */
}

export interface FinalResponseDeltaData {
  delta: string;
  accumulated: string;
}

export interface FinalResponseEndData {
  full_text: string;
  duration_ms?: number;
  duration_display?: string;
}

export interface ResponseFinalData {
  status_code: number;
  user_id: string;
  conversation_id: string;
  question_answer_id: string;
  message: {
    response: string;
    sources?: Record<string, unknown>;
    graph?: unknown[];
  };
  message_is_complete: boolean;
  response_origin: string;
  created_at: string;
}

export interface ErrorData {
  error_type?: string;
  message: string;
  details?: string;
  recoverable: boolean;
}

export interface CancelledData {
  query_id: string;
  message?: string;
  reason?: string;
}

export type SseEvent =
  | BaseEnvelope<"session.started", SessionStartedData>
  | BaseEnvelope<"agent.thinking.start", ThinkingStartData>
  | BaseEnvelope<"agent.thinking.delta", ThinkingDeltaData>
  | BaseEnvelope<"agent.thinking.end", ThinkingEndData>
  | BaseEnvelope<"tool.start", ToolStartData>
  | BaseEnvelope<"tool.end", ToolEndData>
  | BaseEnvelope<"final_response.start", FinalResponseStartData>
  | BaseEnvelope<"final_response.delta", FinalResponseDeltaData>
  | BaseEnvelope<"final_response.end", FinalResponseEndData>
  | BaseEnvelope<"response.final", ResponseFinalData>
  | BaseEnvelope<"session.ended", SessionEndedData>
  | BaseEnvelope<"cancelled", CancelledData>
  | BaseEnvelope<"error", ErrorData>;

export type SseEventName = SseEvent["event"];

export interface StreamRequestBody {
  query: string;
  session_id: string;
  query_id: string;
  user_id?: string;
  reasoning_effort?: "low" | "medium" | "high";
}
