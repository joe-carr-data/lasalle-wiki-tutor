import { useEffect, useState } from "react";
import { Shell } from "./components/Shell";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { Avatar } from "./components/Avatar";
import { ReasoningTimeline } from "./components/ReasoningTimeline";
import { MarkdownAnswer } from "./components/MarkdownAnswer";
import { RotateCw } from "./components/icons";
import { useChatStream } from "./state/useChatStream";
import type { ConversationListItem } from "./components/Sidebar";
import type { Turn } from "./state/useChatStream";

// Lang detection heuristic per plan: Spanish chars + a couple of stopwords.
const ES_HINTS = /[áéíóúñ¿¡]|\b(qué|cómo|cuál|cuáles|para|grado|máster)\b/i;
function detectLang(text: string): "en" | "es" {
  return ES_HINTS.test(text) ? "es" : "en";
}

export default function App() {
  const { state, send, cancel, retry } = useChatStream();
  const [lang, setLang] = useState<"en" | "es">("en");
  const [focusToken, setFocusToken] = useState(0);

  // Cmd/Ctrl+K focuses the composer from anywhere in the app.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isCmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (!isCmdK) return;
      e.preventDefault();
      setFocusToken((n) => n + 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Conversation list is a static placeholder until Task #59/#60 wire the
  // real Mongo-backed history. Empty array shows the "no conversations" hint.
  const conversations: ConversationListItem[] = [];

  function handleSend(text: string) {
    const detected = detectLang(text);
    if (detected !== lang) setLang(detected);
    void send({ text, lang: detected });
  }

  const showEmpty = state.turns.length === 0;
  const lastTurn = state.turns[state.turns.length - 1];
  const canRetry =
    !!lastTurn && (lastTurn.status === "error" || lastTurn.status === "cancelled");

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
          <BasicTurns
            turns={state.turns}
            lang={lang}
            canRetryLast={canRetry}
            onRetry={(turnId) => void retry(turnId)}
          />
        )
      }
      composer={
        <Composer
          lang={lang}
          busy={state.isStreaming}
          focusToken={focusToken}
          onSend={handleSend}
          onCancel={cancel}
        />
      }
    />
  );
}

// Turn renderer — uses the real ReasoningTimeline. The agent answer remains
// raw text until Task #57 adds MarkdownAnswer; the markdown component slots
// in where `{t.answer.markdown}` is rendered today.
function BasicTurns({
  turns,
  lang,
  canRetryLast,
  onRetry,
}: {
  turns: ReturnType<typeof useChatStream>["state"]["turns"];
  lang: "en" | "es";
  canRetryLast: boolean;
  onRetry: (turnId: string) => void;
}) {
  const lastIdx = turns.length - 1;
  return (
    <>
      {turns.map((t, idx) => (
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
              <ReasoningTimeline turn={t} lang={lang} />
              {t.status === "error" ? (
                <div className="bubble bubble-agent answer answer-error">
                  {t.error || (lang === "es" ? "Error" : "Error")}
                </div>
              ) : t.status === "cancelled" && !t.answer.markdown ? (
                <div className="bubble bubble-agent answer answer-cancelled">
                  {lang === "es" ? "Cancelado." : "Cancelled."}
                </div>
              ) : (
                <MarkdownAnswer
                  text={t.answer.markdown}
                  streaming={t.status === "streaming" && !t.answer.done}
                  done={t.answer.done}
                  lang={lang}
                />
              )}
              {idx === lastIdx && canRetryLast && (
                <RetryButton turn={t} lang={lang} onRetry={onRetry} />
              )}
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

function RetryButton({
  turn,
  lang,
  onRetry,
}: {
  turn: Turn;
  lang: "en" | "es";
  onRetry: (turnId: string) => void;
}) {
  return (
    <button
      type="button"
      className="retry-btn"
      onClick={() => onRetry(turn.id)}
    >
      <RotateCw className="ico-sm" />
      <span>{lang === "es" ? "Reintentar" : "Retry"}</span>
    </button>
  );
}
