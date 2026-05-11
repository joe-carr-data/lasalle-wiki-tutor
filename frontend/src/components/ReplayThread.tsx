import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Avatar } from "./Avatar";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { BrainCircuit } from "./icons";
import type { ConversationDetail } from "../api/conversations";

// Replay rendering for a fully-saved conversation. Used by:
//   - the main chat UI (App.tsx) when loading a historical conversation
//   - the admin dashboard (AdminDashboard.tsx) when drilling into a session
// Pure presentation; no streaming, no interaction.

const REPLAY_REMARK_PLUGINS = [remarkGfm];

function ReplayMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={REPLAY_REMARK_PLUGINS}>{text}</ReactMarkdown>
  );
}

export function ReplayThread({
  detail,
  lang,
}: {
  detail: ConversationDetail;
  lang: "en" | "es";
}) {
  const someTurnHasTrace = detail.turns.some((t) => t.has_trace);
  return (
    <>
      {!someTurnHasTrace && detail.turns.length > 0 && (
        <div className="replay-banner">
          {lang === "es"
            ? "Saved · no se puede reproducir el razonamiento."
            : "Saved · cannot replay reasoning."}
        </div>
      )}
      {detail.turns.map((t) => (
        <div key={t.run_id} className="turn">
          <div className="msg msg-user">
            <div className="msg-body">
              <div className="bubble bubble-user">{t.user.text}</div>
            </div>
            <Avatar kind="user" />
          </div>
          <div className="msg msg-agent">
            <Avatar kind="agent" />
            <div className="msg-body">
              {t.has_trace && t.reasoning.length > 0 && (
                <div className="reasoning open">
                  <div className="reasoning-chip" aria-disabled="true">
                    <BrainCircuit className="ico-sm tl-thinking-icon" />
                    <span className="reasoning-chip-label">
                      {lang === "es" ? "Razonamiento guardado" : "Saved reasoning"}
                    </span>
                  </div>
                  <div className="timeline">
                    {t.reasoning.map((step, i) =>
                      step.kind === "thought" ? (
                        <div key={`th-${i}`} className="tl-step tl-thought tl-done">
                          <BrainCircuit className="ico-sm tl-thinking-icon" />
                          <div className="tl-thought-text">
                            <ReplayMarkdown text={step.text || "…"} />
                          </div>
                        </div>
                      ) : (
                        <div key={`tool-${i}`} className="tl-step tl-tool-row tl-done">
                          <span className="tl-dot" />
                          <span className="tl-tool">{step.name}</span>
                          {step.args_display && (
                            <span className="tl-arg">· {step.args_display}</span>
                          )}
                          {step.duration_display && (
                            <span className="tl-meta">{step.duration_display}</span>
                          )}
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}
              <MarkdownAnswer
                text={t.agent.text}
                streaming={false}
                done={true}
                lang={lang}
              />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}
