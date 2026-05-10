// Wiki Tutor — interactive demo app.
// Drives a fake SSE stream so the agent timeline + citations animate realistically.

const { useState, useEffect, useRef, useCallback } = React;

// Hardcoded program cards keyed by canonical id (subset).
const PROGRAMS = {
  "en/bachelor-artificial-intelligence": {
    eyebrow: "Bachelor · Engineering",
    title: "Bachelor's Degree in Artificial Intelligence",
    summary: "A 4-year on-site program covering machine learning, applied AI, data engineering and the ethics of intelligent systems.",
    facts: [
      { label: "240 ECTS", brand: true },
      { label: "4 years" },
      { label: "On-site · Barcelona" },
      { label: "English" },
      { label: "Starts Sept" },
    ],
  },
  "en/bachelor-computer-engineering": {
    eyebrow: "Bachelor · Engineering",
    title: "Bachelor's Degree in Computer Engineering",
    summary: "Broad-based 4-year CS program spanning software engineering, systems, theory, and applied projects with industry partners.",
    facts: [
      { label: "240 ECTS", brand: true },
      { label: "4 years" },
      { label: "On-site · Barcelona" },
      { label: "English" },
      { label: "Starts Sept" },
    ],
  },
  "en/bachelor-animation-and-vfx": {
    eyebrow: "Bachelor · Animation & Digital Arts",
    title: "Bachelor's Degree in Animation & VFX",
    summary: "A 4-year studio-driven program in 3D animation, visual effects, virtual production and game cinematics.",
    facts: [
      { label: "240 ECTS", brand: true },
      { label: "4 years" },
      { label: "On-site" },
      { label: "Spanish / English" },
    ],
  },
  "es/master-ciberseguridad": {
    eyebrow: "Máster · Ingeniería",
    title: "Máster Universitario en Ciberseguridad",
    summary: "Programa de 1 año centrado en seguridad ofensiva y defensiva, gestión de riesgos y cumplimiento normativo.",
    facts: [
      { label: "60 ECTS", brand: true },
      { label: "1 año" },
      { label: "Presencial" },
      { label: "Español" },
    ],
  },
};

// Pre-scripted responses for the demo. Each entry yields a stream of timeline
// steps and a final answer payload (text + citations + optional cards).
const SCRIPTS = {
  "is the ai bachelor in english?": {
    lang: "en",
    steps: [
      { kind: "thought", label: "Detected language", meta: "en", delay: 220 },
      { kind: "tool", tool: "search_programs", arg: "\"AI bachelor english\"", meta: "4 hits", delay: 520 },
      { kind: "tool", tool: "get_program", arg: "en/bachelor-artificial-intelligence", meta: "ok", delay: 480 },
      { kind: "thought", label: "Compose answer", delay: 240 },
    ],
    answer: {
      text: "Yes — the Bachelor's Degree in Artificial Intelligence is taught in English. It's a 4-year, 240 ECTS on-site program in Barcelona, starting in September.",
      citations: ["en/bachelor-artificial-intelligence"],
      cards: ["en/bachelor-artificial-intelligence"],
    },
  },
  "compare cs and ai bachelors": {
    lang: "en",
    steps: [
      { kind: "thought", label: "Detected language", meta: "en", delay: 200 },
      { kind: "tool", tool: "compare_programs", arg: "cs · ai bachelors", meta: "matched 2", delay: 620 },
      { kind: "thought", label: "Compose answer", delay: 240 },
    ],
    answer: {
      text: "Both are 4 years, 240 ECTS, on-site in Barcelona, taught in English. The CS bachelor goes broader across software engineering, systems and theory; the AI bachelor specialises earlier in machine learning, data and applied AI. Curriculum overlap is heaviest in years 1–2.",
      citations: ["en/bachelor-computer-engineering", "en/bachelor-artificial-intelligence"],
      cards: ["en/bachelor-computer-engineering", "en/bachelor-artificial-intelligence"],
    },
  },
  "what courses are in year 2 of cs?": {
    lang: "en",
    steps: [
      { kind: "tool", tool: "get_curriculum", arg: "en/bachelor-computer-engineering", meta: "ok", delay: 600 },
      { kind: "thought", label: "Compose answer", delay: 220 },
    ],
    answer: {
      text: "Year 2 of the Computer Engineering bachelor covers: Algorithms & Data Structures II, Operating Systems, Computer Networks, Databases, Software Engineering I, and a transversal Humanities elective. Around 60 ECTS total.",
      citations: ["en/bachelor-computer-engineering"],
    },
  },
  "careers after animation & vfx?": {
    lang: "en",
    steps: [
      { kind: "tool", tool: "get_program_section", arg: "animation-and-vfx · careers", meta: "ok", delay: 480 },
      { kind: "thought", label: "Compose answer", delay: 200 },
    ],
    answer: {
      text: "Graduates typically work as 3D artists, VFX compositors, technical animators, lighting/look-dev artists, or move into virtual production for film and games. The program lists studio partnerships across Barcelona and Madrid.",
      citations: ["en/bachelor-animation-and-vfx"],
      cards: ["en/bachelor-animation-and-vfx"],
    },
  },
  "másters de ciberseguridad": {
    lang: "es",
    steps: [
      { kind: "thought", label: "Idioma detectado", meta: "es", delay: 220 },
      { kind: "tool", tool: "search_programs", arg: "\"ciberseguridad\" lang=es", meta: "3 hits", delay: 520 },
      { kind: "tool", tool: "get_program", arg: "es/master-ciberseguridad", meta: "ok", delay: 460 },
    ],
    answer: {
      text: "El máster principal en este área es el Máster Universitario en Ciberseguridad — un programa presencial de 60 ECTS, un año, en español, que combina red team, blue team y gestión de riesgos.",
      citations: ["es/master-ciberseguridad"],
      cards: ["es/master-ciberseguridad"],
    },
  },
  "¿cuánto cuesta el grado en ia?": {
    lang: "es",
    steps: [
      { kind: "thought", label: "Idioma detectado", meta: "es", delay: 220 },
      { kind: "tool", tool: "search_programs", arg: "\"grado ia precio\" lang=es", meta: "0 hits", delay: 380 },
    ],
    answer: {
      text: "El catálogo no publica precios. Para matrícula y becas, contacta con admisiones en /es/admisiones — el equipo de admisiones gestiona toda la información económica.",
      citations: [],
    },
  },
};

// Fallback for any free-form input we don't have a script for.
function genericScript(text, lang) {
  return {
    lang,
    steps: [
      { kind: "thought", label: lang === "es" ? "Idioma detectado" : "Detected language", meta: lang, delay: 220 },
      { kind: "tool", tool: "search_programs", arg: `"${text.slice(0, 32)}…"`, meta: "0 hits", delay: 460 },
    ],
    answer: {
      text: lang === "es"
        ? "No tengo una entrada exacta para esa pregunta en el catálogo. Prueba con una pregunta más específica (un programa, asignatura o área), o consulta admisiones en /es/admisiones."
        : "I don't have a catalog match for that exact question. Try something more specific — a program, subject, or area — or reach the admissions team at /en/admissions.",
      citations: [],
    },
  };
}

function pickScript(text) {
  const k = text.trim().toLowerCase();
  if (SCRIPTS[k]) return SCRIPTS[k];
  // try fuzzy contains
  for (const key in SCRIPTS) {
    if (k.includes(key.slice(0, 12))) return SCRIPTS[key];
  }
  // detect language
  const hasES = /[¿áéíóúñ]|cuánto|cómo|grado|máster/.test(k);
  return genericScript(text, hasES ? "es" : "en");
}

function App() {
  const [lang, setLang] = useState("en");
  const [conversations, setConversations] = useState([
    { id: "c1", title: "AI bachelor in English?" },
    { id: "c2", title: "CS vs AI bachelors" },
    { id: "c3", title: "Animation careers" },
  ]);
  const [active, setActive] = useState("c1");
  const [messages, setMessages] = useState([]); // [{role, text?, citations?, cards?, timeline?}]
  const [running, setRunning] = useState(false);
  const threadRef = useRef(null);

  // Re-run lucide on every render so newly-mounted icons render
  useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });

  // Auto-scroll to bottom
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages]);

  const onSend = useCallback(async (text) => {
    if (running) return;
    setRunning(true);

    // user message
    setMessages((m) => [...m, { role: "user", text }]);

    const script = pickScript(text);
    if (script.lang) setLang(script.lang);

    // start agent message with empty timeline
    const agentIdx = await new Promise((res) => {
      setMessages((m) => {
        res(m.length);
        return [...m, { role: "agent", timeline: [], text: "", citations: [], cards: [] }];
      });
    });

    // run steps
    let timeline = [];
    for (let i = 0; i < script.steps.length; i++) {
      const s = script.steps[i];
      // mark prev as done
      timeline = timeline.map((t) => ({ ...t, status: "done" }));
      timeline.push({ ...s, status: "active" });
      setMessages((m) => {
        const copy = [...m];
        copy[agentIdx] = { ...copy[agentIdx], timeline: [...timeline] };
        return copy;
      });
      await wait(s.delay || 400);
    }
    timeline = timeline.map((t) => ({ ...t, status: "done" }));
    setMessages((m) => {
      const copy = [...m];
      copy[agentIdx] = { ...copy[agentIdx], timeline: [...timeline] };
      return copy;
    });

    // stream answer text in chunks
    const chunks = chunkText(script.answer.text);
    let acc = "";
    for (const c of chunks) {
      acc += c;
      setMessages((m) => {
        const copy = [...m];
        copy[agentIdx] = { ...copy[agentIdx], text: acc };
        return copy;
      });
      await wait(28);
    }

    // citations + cards
    setMessages((m) => {
      const copy = [...m];
      copy[agentIdx] = {
        ...copy[agentIdx],
        citations: script.answer.citations || [],
        cards: script.answer.cards || [],
      };
      return copy;
    });

    setRunning(false);
  }, [running]);

  function onNew() {
    const id = "c" + (conversations.length + 1);
    setConversations((c) => [{ id, title: "New conversation" }, ...c]);
    setActive(id);
    setMessages([]);
  }

  return (
    <div className="app">
      <Sidebar
        active={active}
        onSelect={(id) => setActive(id)}
        onNew={onNew}
        conversations={conversations}
        lang={lang}
        onLang={setLang}
      />
      <main className="main">
        <TopBar
          title={conversations.find((c) => c.id === active)?.title || "Wiki Tutor"}
          lang={lang}
        />
        <div className="thread" ref={threadRef}>
          {messages.length === 0 ? (
            <EmptyState lang={lang} onPick={onSend} />
          ) : (
            <div className="thread-inner">
              {messages.map((m, i) => (
                <ChatMessage
                  key={i}
                  role={m.role}
                  citations={m.citations}
                  timeline={m.timeline && m.timeline.length ? m.timeline : null}>
                  {m.text}
                  {m.cards && m.cards.length > 0 && (
                    <div className="msg-cards">
                      {m.cards.map((id) => (
                        <ProgramCard key={id} {...PROGRAMS[id]} id={id} />
                      ))}
                    </div>
                  )}
                </ChatMessage>
              ))}
            </div>
          )}
        </div>
        <Composer onSend={onSend} lang={lang} />
      </main>
    </div>
  );
}

function wait(ms) { return new Promise((res) => setTimeout(res, ms)); }
function chunkText(t) {
  const out = [];
  const words = t.split(/(\s+)/);
  let buf = "";
  for (const w of words) {
    buf += w;
    if (buf.length > 6) { out.push(buf); buf = ""; }
  }
  if (buf) out.push(buf);
  return out;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
