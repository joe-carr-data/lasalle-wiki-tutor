import { useState } from "react";
import { Check } from "./icons";
import { ToolIcon } from "./ToolIcon";
import { truncate } from "../lib/format";
import type { ReasoningStep } from "../state/useChatStream";

type ToolStep = Extract<ReasoningStep, { kind: "tool" }>;

interface ToolCallItemProps {
  step: ToolStep;
}

const ARGS_MAX = 64;
const PREVIEW_MAX = 240;

export function ToolCallItem({ step }: ToolCallItemProps) {
  const [expanded, setExpanded] = useState(false);
  const args = step.argsDisplay ?? "";
  const preview = step.preview ?? "";
  const previewIsLong = preview.length > PREVIEW_MAX;

  const stateClass =
    step.status === "active"
      ? "tl-active"
      : step.status === "error"
        ? "tl-error"
        : "tl-done";

  return (
    <div className={`tl-step tl-tool-row ${stateClass}`}>
      <span className="tl-dot" />
      <ToolIcon name={step.name} className="ico-sm tl-tool-icon" />
      <span className="tl-tool">{step.name}</span>
      {args && <span className="tl-arg">· {truncate(args, ARGS_MAX)}</span>}

      {step.status === "done" && <Check className="ico-sm tl-check" />}

      {step.durationDisplay && (
        <span className="tl-meta">{step.durationDisplay}</span>
      )}

      {preview && (
        <button
          type="button"
          className="tl-preview-toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? "hide" : "result"}
        </button>
      )}

      {preview && (
        <div className={`tl-preview ${expanded ? "open" : ""}`}>
          {expanded || !previewIsLong ? preview : truncate(preview, PREVIEW_MAX)}
        </div>
      )}
    </div>
  );
}
