import { useEffect, useMemo, useRef, useState } from "react";
import { Shell } from "./components/Shell";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { Avatar } from "./components/Avatar";
import { ReasoningTimeline } from "./components/ReasoningTimeline";
import { MarkdownAnswer } from "./components/MarkdownAnswer";
import { ConfirmDelete } from "./components/ConfirmDelete";
import { JumpToLatest } from "./components/JumpToLatest";
import { ReplayThread } from "./components/ReplayThread";
import { RotateCw } from "./components/icons";
import { useChatStream } from "./state/useChatStream";
import { useConversations } from "./state/useConversations";
import { useStickyScroll } from "./state/useStickyScroll";
import { getUserId } from "./lib/userId";
import type { Turn } from "./state/useChatStream";

const ES_HINTS = /[áéíóúñ¿¡]|\b(qué|cómo|cuál|cuáles|para|grado|máster)\b/i;
function detectLang(text: string): "en" | "es" {
  return ES_HINTS.test(text) ? "es" : "en";
}

export default function App() {
  const userId = useMemo(() => getUserId(), []);
  const { state, send, cancel, retry, resetSession } = useChatStream();
  const conversations = useConversations(userId);
  const [lang, setLang] = useState<"en" | "es">("en");
  const [focusToken, setFocusToken] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  // Mobile sidebar visibility. Closed by default; the topbar hamburger
  // toggles it. Closing happens automatically when the user taps the
  // backdrop, picks a conversation, or hits New chat.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Cmd/Ctrl+K focuses the composer.
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

  // After every successful turn, refresh the sidebar so a brand-new
  // conversation row appears with its server-assigned title.
  //
  // We hold `conversations` in a ref so the effect can read its current
  // callbacks without depending on the hook's return-object identity —
  // that object is a fresh literal every render, and listing it as a
  // dep used to re-fire the effect on every render, hammering the API
  // in a tight loop.
  const conversationsRef = useRef(conversations);
  conversationsRef.current = conversations;
  const lastTurn = state.turns[state.turns.length - 1];
  const lastDoneTurnId = lastTurn?.status === "done" ? lastTurn.id : null;
  useEffect(() => {
    if (!lastDoneTurnId) return;
    void conversationsRef.current.refresh();
    if (state.sessionId) conversationsRef.current.setActive(state.sessionId);
  }, [lastDoneTurnId, state.sessionId]);

  function handleSend(text: string) {
    const detected = detectLang(text);
    if (detected !== lang) setLang(detected);
    // Make sure the sidebar reflects this conversation immediately —
    // useChatStream will mint a session id if we don't have one yet, but
    // we need it client-side now to insert the placeholder row. So mint
    // the id here, set it as the active session, and only then call send.
    let sid = state.sessionId;
    if (!sid) {
      sid = crypto.randomUUID();
      resetSession(sid);
    }
    conversations.optimisticInsert(sid, text, detected);
    void send({ text, lang: detected, userId, sessionId: sid });
  }

  function handleNewChat() {
    cancel();
    const fresh = crypto.randomUUID();
    resetSession(fresh);
    conversations.setActive(fresh);
    void conversations.select(null);
    setSidebarOpen(false);
  }

  function handleSelectConversation(id: string) {
    setSidebarOpen(false);
    if (id === state.sessionId) return;
    cancel();
    resetSession(id);
    void conversations.select(id);
  }

  function handleRename(id: string, title: string) {
    void conversations.rename(id, title);
  }

  function handleRequestDelete(id: string) {
    const target = conversations.items.find((c) => c.id === id);
    if (!target) return;
    setPendingDelete({ id, title: target.title });
  }

  function confirmDelete() {
    if (!pendingDelete) return;
    void conversations.remove(pendingDelete.id);
    if (state.sessionId === pendingDelete.id) {
      handleNewChat();
    }
    setPendingDelete(null);
  }

  // While a saved conversation is hydrated and there are no in-memory turns,
  // we render replay turns from `conversations.detail`. As soon as the user
  // sends a new message in this session, in-memory turns take precedence.
  const replayTurns =
    state.turns.length === 0 && conversations.detail ? conversations.detail : null;
  const showEmpty = state.turns.length === 0 && !replayTurns;
  const canRetry =
    !!lastTurn && (lastTurn.status === "error" || lastTurn.status === "cancelled");

  // Sticky-bottom scroll: re-pin to the bottom while the user is at the
  // bottom and content keeps appending. The contentTick changes when:
  //   - a new turn is added
  //   - the active turn's answer markdown grows
  //   - reasoning steps grow
  // We compose a cheap signature from those signals.
  const lastTurnSignature = lastTurn
    ? `${lastTurn.id}:${lastTurn.reasoning.length}:${lastTurn.answer.markdown.length}`
    : "";
  const contentTick = `${state.turns.length}:${lastTurnSignature}`;
  const { ref: scrollRef, atBottom, scrollToBottom } = useStickyScroll<HTMLDivElement>({
    contentTick,
  });

  return (
    <>
      <Shell
        ref={scrollRef}
        sidebarOpen={sidebarOpen}
        onSidebarClose={() => setSidebarOpen(false)}
        sidebar={
          <Sidebar
            conversations={conversations.items.map((c) => ({ id: c.id, title: c.title }))}
            activeId={state.sessionId}
            lang={lang}
            loading={conversations.loadingList}
            onSelect={handleSelectConversation}
            onNewChat={handleNewChat}
            onLangChange={setLang}
            onRename={handleRename}
            onRequestDelete={handleRequestDelete}
          />
        }
        topBar={
          <TopBar
            title="Wiki Tutor"
            lang={lang}
            onMenuClick={() => setSidebarOpen((v) => !v)}
          />
        }
        thread={
          showEmpty ? (
            <EmptyState lang={lang} onPick={handleSend} />
          ) : replayTurns ? (
            <ReplayThread detail={replayTurns} lang={lang} />
          ) : (
            <BasicTurns
              turns={state.turns}
              lang={lang}
              canRetryLast={canRetry}
              onRetry={(turnId) => void retry(turnId)}
            />
          )
        }
        threadOverlay={
          <JumpToLatest
            visible={!atBottom && (state.turns.length > 0 || !!replayTurns)}
            lang={lang}
            onJump={() => scrollToBottom(true)}
          />
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
      {pendingDelete && (
        <ConfirmDelete
          title={pendingDelete.title}
          lang={lang}
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}

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
    <button type="button" className="retry-btn" onClick={() => onRetry(turn.id)}>
      <RotateCw className="ico-sm" />
      <span>{lang === "es" ? "Reintentar" : "Retry"}</span>
    </button>
  );
}

