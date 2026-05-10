import { authedFetch } from "../lib/auth";
import type { SseEvent, StreamRequestBody } from "./types";

const STREAM_ENDPOINT = "/api/wiki-tutor/v1/query/stream";

/**
 * Network/transport-level failure that the parser couldn't translate into
 * a server-emitted `error` SSE event. Caller decides whether to retry.
 *
 * `recoverable` mirrors the server's `error.recoverable` semantics: true
 * means it's safe to auto-reconnect *iff* no `final_response.delta` has
 * been observed yet on this call.
 */
export class StreamError extends Error {
  readonly status?: number;
  readonly recoverable: boolean;

  constructor(message: string, opts: { status?: number; recoverable?: boolean } = {}) {
    super(message);
    this.name = "StreamError";
    this.status = opts.status;
    this.recoverable = opts.recoverable ?? false;
  }
}

interface PendingFrame {
  event?: string;
  data: string[]; // multi-line `data:` per SSE spec, joined with "\n"
}

function freshFrame(): PendingFrame {
  return { event: undefined, data: [] };
}

/**
 * SSE parser that handles the non-trivial corners of the wire format:
 *  - LF and CRLF line endings
 *  - multi-line `data:` frames (joined with "\n" per spec)
 *  - trailing buffered event when the stream ends without a final blank line
 *  - non-200 / non-event-stream content-type → typed StreamError
 *
 * Yields envelopes shaped like `{ event, data }` where `data` is the parsed
 * JSON payload. Unknown event names are still yielded — the reducer chooses
 * to ignore them. Malformed JSON inside a frame surfaces as a synthetic
 * `error` event instead of throwing, so the upstream consumer can decide.
 */
export async function* streamQuery(
  body: StreamRequestBody,
  signal: AbortSignal,
): AsyncIterable<SseEvent> {
  const res = await authedFetch(STREAM_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    throw new StreamError(`HTTP ${res.status} from ${STREAM_ENDPOINT}`, {
      status: res.status,
      recoverable: res.status >= 500 && res.status < 600,
    });
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new StreamError(
      `Unexpected content-type "${contentType}" — expected text/event-stream`,
      { status: res.status, recoverable: false },
    );
  }

  if (!res.body) {
    throw new StreamError("Response body is empty (no readable stream)", { recoverable: false });
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let pending: PendingFrame = freshFrame();

  const flushFrame = function* (frame: PendingFrame): Generator<SseEvent> {
    if (!frame.event || frame.data.length === 0) return;
    const raw = frame.data.join("\n");
    let parsed: { data?: unknown } | null;
    try {
      parsed = JSON.parse(raw) as { data?: unknown } | null;
    } catch (err) {
      // Bad JSON shouldn't kill the stream — surface as a synthetic error
      // event and keep going so the reducer can decide to terminate.
      yield {
        event: "error",
        data: {
          error_type: "parse_error",
          message: `Failed to parse SSE data for event "${frame.event}": ${(err as Error).message}`,
          recoverable: false,
        },
      } as SseEvent;
      return;
    }
    // The server wraps each event in an envelope:
    //   { event_type, event_id, timestamp, elapsed_ms, correlation_id,
    //     agent, data: { ...payload } }
    // The reducer wants the inner payload directly under `event.data`, so
    // we unwrap here. Anything else (server emitted a non-enveloped JSON
    // object) is yielded as-is.
    const payload =
      parsed && typeof parsed === "object" && "data" in parsed
        ? parsed.data
        : parsed;
    yield { event: frame.event, data: payload } as SseEvent;
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      // Normalize CRLF and bare CR to LF so a single split works.
      buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line === "") {
          // Blank line terminates the frame.
          for (const ev of flushFrame(pending)) yield ev;
          pending = freshFrame();
          continue;
        }
        if (line.startsWith(":")) {
          // Comment / heartbeat — ignore.
          continue;
        }
        if (line.startsWith("event:")) {
          pending.event = line.slice(6).trimStart();
          continue;
        }
        if (line.startsWith("data:")) {
          // Per spec: strip a single leading space if present.
          let chunk = line.slice(5);
          if (chunk.startsWith(" ")) chunk = chunk.slice(1);
          pending.data.push(chunk);
          continue;
        }
        // Unknown field (id:, retry:, …) — ignore.
      }
    }

    // Flush trailing decoder bytes and any final buffered line.
    const tail = decoder.decode().replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (tail) buffer += tail;
    if (buffer) {
      // No terminator was seen; treat the dangling buffer as a final line.
      const line = buffer;
      buffer = "";
      if (line.startsWith("event:")) {
        pending.event = line.slice(6).trimStart();
      } else if (line.startsWith("data:")) {
        let chunk = line.slice(5);
        if (chunk.startsWith(" ")) chunk = chunk.slice(1);
        pending.data.push(chunk);
      }
    }
    for (const ev of flushFrame(pending)) yield ev;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* lock may already be released on abort */
    }
  }
}
