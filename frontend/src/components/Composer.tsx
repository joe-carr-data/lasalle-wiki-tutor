import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, Square } from "./icons";

interface ComposerProps {
  lang: "en" | "es";
  busy: boolean;
  /** Bump to programmatically focus the textarea (e.g. global Cmd+K). */
  focusToken?: number;
  onSend: (text: string) => void;
  onCancel: () => void;
}

const PLACEHOLDERS: Record<"en" | "es", string> = {
  en: "Ask about programs, courses, careers…",
  es: "Pregunta por programas, cursos, salidas…",
};

const META_COPY: Record<"en" | "es", string> = {
  en: "Grounded in the salleurl.edu catalog",
  es: "Basado en el catálogo de salleurl.edu",
};

export function Composer({ lang, busy, focusToken, onSend, onCancel }: ComposerProps) {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Re-autosize when text is cleared programmatically.
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  useEffect(() => {
    if (focusToken === undefined) return;
    taRef.current?.focus();
  }, [focusToken]);

  function submit() {
    if (busy) return;
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape" && busy) {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={taRef}
          rows={1}
          value={text}
          placeholder={PLACEHOLDERS[lang]}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          aria-label={lang === "es" ? "Mensaje" : "Message"}
        />
        <div className="composer-row">
          <div className="composer-meta">
            <BookOpen className="ico-sm" />
            <span>{META_COPY[lang]}</span>
          </div>
          {busy ? (
            <button
              className="send-btn send-btn-cancel"
              onClick={onCancel}
              aria-label={lang === "es" ? "Cancelar" : "Cancel"}
            >
              <Square className="ico-sm" />
            </button>
          ) : (
            <button
              className="send-btn"
              disabled={!text.trim()}
              onClick={submit}
              aria-label={lang === "es" ? "Enviar" : "Send"}
            >
              <ArrowUp className="ico-sm" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
