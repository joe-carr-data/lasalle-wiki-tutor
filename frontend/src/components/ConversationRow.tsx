import { useEffect, useRef, useState } from "react";
import { MessageSquare, Pencil, Trash2 } from "./icons";

interface ConversationRowProps {
  id: string;
  title: string;
  active: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onRequestDelete: (id: string) => void;
}

export function ConversationRow({
  id,
  title,
  active,
  onSelect,
  onRename,
  onRequestDelete,
}: ConversationRowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(title);
      // defer focus so the input is mounted
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      });
    }
  }, [editing, title]);

  function commit() {
    const cleaned = draft.trim();
    setEditing(false);
    if (!cleaned || cleaned === title) return;
    onRename(id, cleaned);
  }

  function cancel() {
    setEditing(false);
    setDraft(title);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  }

  if (editing) {
    return (
      <div className={`sb-item sb-item-editing${active ? " active" : ""}`}>
        <MessageSquare className="ico-sm" />
        <input
          ref={inputRef}
          className="sb-item-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          onBlur={commit}
          maxLength={80}
        />
      </div>
    );
  }

  return (
    <div
      className={`sb-item${active ? " active" : ""}`}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(id);
        }
      }}
    >
      <MessageSquare className="ico-sm" />
      <span className="sb-item-title">{title}</span>
      <button
        type="button"
        className="sb-item-action"
        aria-label="Rename"
        onClick={(e) => {
          e.stopPropagation();
          setEditing(true);
        }}
      >
        <Pencil className="ico-sm" />
      </button>
      <button
        type="button"
        className="sb-item-action sb-item-action-danger"
        aria-label="Delete"
        onClick={(e) => {
          e.stopPropagation();
          onRequestDelete(id);
        }}
      >
        <Trash2 className="ico-sm" />
      </button>
    </div>
  );
}
