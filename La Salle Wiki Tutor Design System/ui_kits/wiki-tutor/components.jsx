// Wiki Tutor — shared chat components.
// Globals: TutorShell, Sidebar, ChatMessage, AgentTimeline, ProgramCard, Composer, CitationChip
// Loaded as <script type="text/babel" src="components.jsx"></script>

const { useState, useEffect, useRef } = React;

// ----- Citation chip -----
function CitationChip({ id, onClick }) {
  return (
    <span className="cite-chip" onClick={onClick} role="button" tabIndex={0}>
      <span className="cite-dot" />
      {id}
    </span>
  );
}

// ----- Avatar -----
function Avatar({ kind = "agent" }) {
  if (kind === "user") {
    return <div className="avatar avatar-user">You</div>;
  }
  return (
    <div className="avatar avatar-agent" aria-label="La Salle Wiki Tutor">
      <span className="avatar-ls">LS</span>
    </div>
  );
}

// ----- Single message bubble -----
function ChatMessage({ role, children, citations = [], timeline = null }) {
  const isUser = role === "user";
  return (
    <div className={`msg msg-${role}`}>
      {!isUser && <Avatar kind="agent" />}
      <div className="msg-body">
        {timeline && <AgentTimeline steps={timeline} />}
        <div className={`bubble bubble-${role}`}>{children}</div>
        {citations.length > 0 && (
          <div className="cite-row">
            {citations.map((c) => <CitationChip key={c} id={c} />)}
          </div>
        )}
      </div>
      {isUser && <Avatar kind="user" />}
    </div>
  );
}

// ----- Streaming "agent thinking" timeline -----
function AgentTimeline({ steps }) {
  return (
    <div className="timeline">
      {steps.map((s, i) => (
        <div key={i} className={`tl-step tl-${s.status}`}>
          <span className="tl-dot" />
          {s.kind === "tool" ? (
            <>
              <span className="tl-tool">{s.tool}</span>
              {s.arg && <span className="tl-arg">· {s.arg}</span>}
            </>
          ) : (
            <span>{s.label}</span>
          )}
          {s.meta && <span className="tl-meta">{s.meta}</span>}
        </div>
      ))}
    </div>
  );
}

// ----- Program card (used inline in answers + side rails) -----
function ProgramCard({ eyebrow, title, summary, facts = [], id }) {
  return (
    <div className="prog-card">
      <div className="prog-eyebrow">{eyebrow}</div>
      <div className="prog-title">{title}</div>
      {summary && <div className="prog-summary">{summary}</div>}
      <div className="prog-facts">
        {facts.map((f, i) => (
          <span key={i} className={`fact${f.brand ? " fact-brand" : ""}`}>{f.label}</span>
        ))}
      </div>
      <div className="prog-id">{id}</div>
    </div>
  );
}

// ----- Sidebar -----
function Sidebar({ active, onSelect, onNew, conversations, lang, onLang }) {
  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <div className="sb-mark">LS</div>
        <div className="sb-stack">
          <div className="sb-title">Wiki Tutor</div>
          <div className="sb-sub">La Salle BCN · URL</div>
        </div>
      </div>
      <button className="btn btn-primary sb-new" onClick={onNew}>
        <i data-lucide="plus" className="ico-sm"></i> New chat
      </button>
      <div className="sb-section">Conversations</div>
      <div className="sb-list">
        {conversations.map((c) => (
          <button
            key={c.id}
            className={`sb-item${c.id === active ? " active" : ""}`}
            onClick={() => onSelect(c.id)}>
            <i data-lucide="message-square" className="ico-sm"></i>
            <span className="sb-item-title">{c.title}</span>
          </button>
        ))}
      </div>
      <div className="sb-foot">
        <div className="lang-toggle">
          <button className={lang === "en" ? "on" : ""} onClick={() => onLang("en")}>EN</button>
          <button className={lang === "es" ? "on" : ""} onClick={() => onLang("es")}>ES</button>
        </div>
        <a className="sb-link" href="#">Admissions →</a>
      </div>
    </aside>
  );
}

// ----- Composer -----
function Composer({ onSend, lang }) {
  const [text, setText] = useState("");
  const ref = useRef(null);
  const placeholders = {
    en: "Ask about programs, courses, careers…",
    es: "Pregunta por programas, cursos, salidas…"
  };

  function submit() {
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
    if (ref.current) ref.current.style.height = "auto";
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function autosize(e) {
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  }

  const suggestionsByLang = {
    en: [
      "Is the AI bachelor in English?",
      "Difference between CS and AI bachelors?",
      "What courses in year 2 of CS?",
      "Best masters for cybersecurity careers?"
    ],
    es: [
      "¿Cuánto dura el grado en IA?",
      "Diferencia entre Ingeniería Informática e IA",
      "Másters de ciberseguridad",
      "Cursos de verano sobre IA"
    ]
  };

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          placeholder={placeholders[lang]}
          onChange={(e) => { setText(e.target.value); autosize(e); }}
          onKeyDown={onKey} />
        <div className="composer-row">
          <div className="composer-meta">
            <i data-lucide="book-open" className="ico-sm"></i>
            <span>Grounded in the salleurl.edu catalog</span>
          </div>
          <button className="send-btn" disabled={!text.trim()} onClick={submit} aria-label="Send">
            <i data-lucide="arrow-up" className="ico-sm"></i>
          </button>
        </div>
      </div>
      <div className="suggestions">
        {suggestionsByLang[lang].map((s, i) => (
          <button key={i} className="sugg" onClick={() => onSend(s)}>{s}</button>
        ))}
      </div>
    </div>
  );
}

// ----- Top bar -----
function TopBar({ title, lang }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-title">{title}</div>
        <span className="topbar-tag">{lang.toUpperCase()}</span>
      </div>
      <div className="topbar-right">
        <button className="icon-btn" aria-label="Share"><i data-lucide="share-2"></i></button>
        <button className="icon-btn" aria-label="Settings"><i data-lucide="settings"></i></button>
      </div>
    </header>
  );
}

// ----- Empty state -----
function EmptyState({ lang, onPick }) {
  const copy = lang === "en"
    ? {
        eyebrow: "La Salle Wiki Tutor",
        h: "Ask about any program, course, or career path.",
        sub: "Grounded in the salleurl.edu catalog. The tutor cites real program ids, and points you to admissions for tuition.",
        starters: [
          { ico: "compass",  text: "I'm into tech — what could I study?" },
          { ico: "git-compare-arrows", text: "Compare CS and AI bachelors" },
          { ico: "list-checks", text: "What courses are in year 2 of CS?" },
          { ico: "briefcase",  text: "Careers after Animation & VFX?" },
        ]
      }
    : {
        eyebrow: "Tutor del Wiki de La Salle",
        h: "Pregunta sobre cualquier programa, curso o salida profesional.",
        sub: "Basado en el catálogo de salleurl.edu. El tutor cita ids reales y te deriva a admisiones para precios.",
        starters: [
          { ico: "compass", text: "Me interesa la tecnología — ¿qué puedo estudiar?" },
          { ico: "git-compare-arrows", text: "Compara los grados de Informática e IA" },
          { ico: "list-checks", text: "¿Qué asignaturas hay en 2º de Informática?" },
          { ico: "briefcase", text: "Salidas tras Animación y VFX" },
        ]
      };
  return (
    <div className="empty">
      <div className="empty-mark">LS</div>
      <div className="empty-eyebrow">{copy.eyebrow}</div>
      <h1 className="empty-h">{copy.h}</h1>
      <p className="empty-sub">{copy.sub}</p>
      <div className="starter-grid">
        {copy.starters.map((s, i) => (
          <button key={i} className="starter" onClick={() => onPick(s.text)}>
            <i data-lucide={s.ico} className="ico"></i>
            <span>{s.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, {
  CitationChip, Avatar, ChatMessage, AgentTimeline, ProgramCard,
  Sidebar, Composer, TopBar, EmptyState
});
