import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "./icons";
import { ToolCallItem } from "./ToolCallItem";
import { summarizeReasoning } from "../lib/format";
import type { ReasoningStep, Turn } from "../state/useChatStream";

interface ReasoningTimelineProps {
  turn: Turn;
  lang: "en" | "es";
}

export function ReasoningTimeline({ turn, lang }: ReasoningTimelineProps) {
  const isStreaming = turn.status === "streaming";
  const hasSteps = turn.reasoning.length > 0;

  // Auto-collapse once streaming finishes; user can still expand manually.
  const [open, setOpen] = useState(true);
  const autoCollapsedRef = useRef(false);
  useEffect(() => {
    if (!isStreaming && !autoCollapsedRef.current && hasSteps) {
      autoCollapsedRef.current = true;
      // Defer one frame so the user sees the final state before it folds.
      const t = window.setTimeout(() => setOpen(false), 350);
      return () => window.clearTimeout(t);
    }
  }, [isStreaming, hasSteps]);

  if (!hasSteps && !isStreaming) return null;

  // Pre-stream microcopy: the agent has accepted the turn but hasn't emitted
  // a thinking event yet. Shows a single muted row so the agent bubble has
  // *something* visible during the cold-start window.
  if (!hasSteps && isStreaming) {
    return (
      <div className="reasoning">
        <div className="timeline">
          <div className="tl-step tl-active tl-prelude">
            <Loader2 className="ico-sm tl-spin" />
            <span>{lang === "es" ? "Pensando…" : "Thinking…"}</span>
          </div>
        </div>
      </div>
    );
  }

  const toolCount = turn.reasoning.filter((s) => s.kind === "tool").length;
  const totalMs =
    (turn.finishedAt ?? Date.now()) - turn.startedAt;
  const summary = summarizeReasoning({ totalMs, toolCount, lang });

  return (
    <div className={`reasoning ${open ? "open" : "collapsed"}`}>
      <button
        type="button"
        className="reasoning-chip"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="ico-sm" />
        ) : (
          <ChevronRight className="ico-sm" />
        )}
        <span className="reasoning-chip-label">
          {isStreaming ? (lang === "es" ? "Razonando" : "Reasoning") : summary}
        </span>
        {isStreaming && <Loader2 className="ico-sm tl-spin" />}
      </button>

      {open && (
        <div className="timeline">
          {turn.reasoning.map((step) =>
            step.kind === "thought" ? (
              <ThoughtItem key={step.id} step={step} />
            ) : (
              <ToolCallItem key={step.id} step={step} />
            ),
          )}
        </div>
      )}
    </div>
  );
}

interface ThoughtItemProps {
  step: Extract<ReasoningStep, { kind: "thought" }>;
}

function ThoughtItem({ step }: ThoughtItemProps) {
  const stateClass = step.status === "active" ? "tl-active" : "tl-done";
  return (
    <div className={`tl-step tl-thought ${stateClass}`}>
      <span className="tl-dot" />
      <span className="tl-thought-text">{step.text || "…"}</span>
    </div>
  );
}
