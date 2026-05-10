import { useState } from "react";
import { Shell } from "./components/Shell";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { Avatar } from "./components/Avatar";
import { useChatStream } from "./state/useChatStream";
import type { ConversationListItem } from "./components/Sidebar";

// Lang detection heuristic per plan: Spanish chars + a couple of stopwords.
const ES_HINTS = /[áéíóúñ¿¡]|\b(qué|cómo|cuál|cuáles|para|grado|máster)\b/i;
function detectLang(text: string): "en" | "es" {
  return ES_HINTS.test(text) ? "es" : "en";
}

export default function App() {
  const { state, send, cancel } = useChatStream();
  const [lang, setLang] = useState<"en" | "es">("en");

  // Conversation list is a static placeholder until Task #59/#60 wire the
  // real Mongo-backed history. Empty array shows the "no conversations" hint.
  const conversations: ConversationListItem[] = [];

  function handleSend(text: string) {
    const detected = detectLang(text);
    if (detected !== lang) setLang(detected);
    void send({ text, lang: detected });
  }

  const showEmpty = state.turns.length === 0;

  return (
    <Shell
      sidebar={
        <Sidebar
          conversations={conversations}
          activeId={state.sessionId}
          lang={lang}
          onSelect={() => {
            /* hooked up in Task #60 */
          }}
          onNewChat={() => window.location.reload()}
          onLangChange={setLang}
        />
      }
      topBar={<TopBar title="Wiki Tutor" lang={lang} />}
      thread={
        showEmpty ? (
          <EmptyState lang={lang} onPick={handleSend} />
        ) : (
          <BasicTurns turns={state.turns} />
        )
      }
      composer={
        <Composer
          lang={lang}
          busy={state.isStreaming}
          onSend={handleSend}
          onCancel={cancel}
        />
      }
    />
  );
}

// Minimal turn renderer until Task #56/#57 add the real ReasoningTimeline +
// MarkdownAnswer. This proves the streaming pipeline end-to-end.
function BasicTurns({ turns }: { turns: ReturnType<typeof useChatStream>["state"]["turns"] }) {
  return (
    <>
      {turns.map((t) => (
        <div key={t.id} className="turn">
          <div className="msg msg-user">
            <div className="msg-body">
              <div className="bubble bubble-user">{t.user.text}</div>
            </div>
            <Avatar kind="user" />
          </div>
          <div className="msg msg-agent">
            <Avatar kind="agent" />
            <div className="msg-body">
              {t.reasoning.length > 0 && (
                <div className="timeline">
                  {t.reasoning.map((s) => (
                    <div
                      key={s.id}
                      className={`tl-step tl-${s.status === "active" ? "active" : "done"}`}
                    >
                      <span className="tl-dot" />
                      {s.kind === "tool" ? (
                        <>
                          <span className="tl-tool">{s.name}</span>
                          {s.argsDisplay && <span className="tl-arg">· {s.argsDisplay}</span>}
                          {s.durationDisplay && <span className="tl-meta">{s.durationDisplay}</span>}
                        </>
                      ) : (
                        <span>{s.text || "Thinking…"}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div className="bubble bubble-agent">
                {t.answer.markdown ||
                  (t.status === "streaming" ? "…" : t.error || "")}
              </div>
            </div>
          </div>
        </div>
      ))}
    </>
  );
}
