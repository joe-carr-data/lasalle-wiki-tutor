import { useEffect } from "react";

interface ConfirmDeleteProps {
  title: string;
  lang: "en" | "es";
  onConfirm: () => void;
  onCancel: () => void;
}

const COPY = {
  en: {
    heading: "Delete this conversation?",
    body: "This can’t be undone.",
    confirm: "Delete",
    cancel: "Cancel",
  },
  es: {
    heading: "¿Borrar esta conversación?",
    body: "Esta acción no se puede deshacer.",
    confirm: "Borrar",
    cancel: "Cancelar",
  },
};

export function ConfirmDelete({ title, lang, onConfirm, onCancel }: ConfirmDeleteProps) {
  const copy = COPY[lang];

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Enter") {
        e.preventDefault();
        onConfirm();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, onConfirm]);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-delete-heading"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="confirm-delete-heading" className="modal-heading">
          {copy.heading}
        </h3>
        <p className="modal-title">"{title}"</p>
        <p className="modal-body">{copy.body}</p>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            {copy.cancel}
          </button>
          <button type="button" className="btn-danger" onClick={onConfirm} autoFocus>
            {copy.confirm}
          </button>
        </div>
      </div>
    </div>
  );
}
