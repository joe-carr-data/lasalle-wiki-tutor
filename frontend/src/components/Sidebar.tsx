import { LogOut, Plus } from "./icons";
import { ConversationRow } from "./ConversationRow";
import { clearStoredToken } from "../lib/auth";

export interface ConversationListItem {
  id: string;
  title: string;
}

interface SidebarProps {
  conversations: ConversationListItem[];
  activeId: string | null;
  lang: "en" | "es";
  loading?: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onLangChange: (lang: "en" | "es") => void;
  onRename: (id: string, title: string) => void;
  onRequestDelete: (id: string) => void;
}

export function Sidebar({
  conversations,
  activeId,
  lang,
  loading,
  onSelect,
  onNewChat,
  onLangChange,
  onRename,
  onRequestDelete,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <div className="sb-mark">LS</div>
        <div className="sb-stack">
          <div className="sb-title">Wiki Tutor</div>
          <div className="sb-sub">La Salle BCN · URL</div>
        </div>
      </div>

      <button className="sb-new" onClick={onNewChat}>
        <Plus className="ico-sm" /> {lang === "es" ? "Nueva conversación" : "New chat"}
      </button>

      <div className="sb-section">
        {lang === "es" ? "Conversaciones" : "Conversations"}
      </div>
      <div className="sb-list">
        {!loading && conversations.length === 0 && (
          <div className="sb-empty">
            {lang === "es"
              ? "Sin conversaciones todavía."
              : "No conversations yet."}
          </div>
        )}
        {conversations.map((c) => (
          <ConversationRow
            key={c.id}
            id={c.id}
            title={c.title}
            active={c.id === activeId}
            onSelect={onSelect}
            onRename={onRename}
            onRequestDelete={onRequestDelete}
          />
        ))}
      </div>

      <div className="sb-foot">
        <div className="lang-toggle" role="group" aria-label="Language">
          <button
            className={lang === "en" ? "on" : ""}
            aria-pressed={lang === "en"}
            onClick={() => onLangChange("en")}
          >
            EN
          </button>
          <button
            className={lang === "es" ? "on" : ""}
            aria-pressed={lang === "es"}
            onClick={() => onLangChange("es")}
          >
            ES
          </button>
        </div>
        <a
          className="sb-link"
          href="https://www.salleurl.edu/en/admissions"
          target="_blank"
          rel="noreferrer"
        >
          Admissions →
        </a>
      </div>

      <button
        type="button"
        className="sb-logout"
        onClick={clearStoredToken}
        aria-label={lang === "es" ? "Cerrar sesión" : "Sign out"}
        title={lang === "es" ? "Cerrar sesión" : "Sign out"}
      >
        <LogOut className="ico-sm" />
        <span>{lang === "es" ? "Cerrar sesión" : "Sign out"}</span>
      </button>
    </aside>
  );
}
