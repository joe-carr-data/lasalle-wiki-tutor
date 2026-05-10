import { memo, useDeferredValue, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { CitationChip } from "./CitationChip";
import { extractCitations } from "../lib/citations";

interface MarkdownAnswerProps {
  text: string;
  streaming: boolean;
  done: boolean;
  showSources?: boolean;
  lang: "en" | "es";
}

const COMPONENTS: Components = {
  a({ href, children, ...rest }) {
    const safeHref = typeof href === "string" ? href : "";
    const isExternal = /^https?:\/\//.test(safeHref);
    return (
      <a
        href={safeHref}
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noreferrer" : undefined}
        {...rest}
      >
        {children}
        {isExternal && <span className="ext-link" aria-hidden="true">↗</span>}
      </a>
    );
  },
  // Strip raw HTML to be safe; remark-gfm + plain markdown is enough.
  // Tables / lists / code fences / blockquotes all get default rendering.
};

const REMARK_PLUGINS = [remarkGfm];

const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
});

export function MarkdownAnswer({
  text,
  streaming,
  done,
  showSources = true,
  lang,
}: MarkdownAnswerProps) {
  // Coerce to string defensively — react-markdown crashes on undefined,
  // which would blank the entire app. Any non-string upstream bug is
  // contained here.
  const safeText = typeof text === "string" ? text : "";
  // The expensive react-markdown parse runs on a deferred snapshot of
  // the text. While streaming this lets React skip intermediate parses
  // when deltas arrive faster than the browser can paint, removing the
  // visible jitter without dropping any final tokens — the deferred
  // value always settles on the latest text within a frame or two.
  const deferredText = useDeferredValue(safeText);
  const citations = useMemo(
    () => (showSources && done ? extractCitations(safeText) : []),
    [showSources, done, safeText],
  );

  if (!safeText && streaming) {
    // Pre-token state — the timeline already shows "Thinking…" so the bubble
    // stays minimal here. A typing dot keeps the UI responsive.
    return (
      <div className="answer answer-prelude" aria-live="polite">
        <span className="answer-typing">
          <span /> <span /> <span />
        </span>
      </div>
    );
  }

  return (
    <div className={`answer ${streaming ? "answer-streaming" : ""}`} aria-live="polite">
      <div className="answer-md">
        <Markdown text={deferredText} />
        {streaming && <span className="answer-caret" aria-hidden="true" />}
      </div>
      {citations.length > 0 && (
        <div className="answer-sources">
          <div className="answer-sources-label">
            {lang === "es" ? "Fuentes" : "Sources"}
          </div>
          <div className="cite-row">
            {citations.map((c) => (
              <CitationChip key={c.href} href={c.href} label={c.label} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
