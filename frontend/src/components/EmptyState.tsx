import { Briefcase, Compass, GitCompareArrows, ListChecks } from "./icons";
import type { LucideIcon } from "lucide-react";
import heroImage from "../assets/be-real-be-you.jpg";

interface EmptyStateProps {
  lang: "en" | "es";
  onPick: (text: string) => void;
}

interface Starter {
  Icon: LucideIcon;
  text: string;
}

const COPY: Record<
  "en" | "es",
  { eyebrow: string; h: string; sub: string; starters: Starter[] }
> = {
  en: {
    eyebrow: "La Salle Wiki Tutor",
    h: "Ask about any program, course, or career path.",
    sub:
      "Grounded in the salleurl.edu catalog. The tutor cites real program pages and points you to admissions for tuition.",
    starters: [
      { Icon: Compass, text: "I'm into tech — what could I study?" },
      { Icon: GitCompareArrows, text: "Compare CS and AI bachelors" },
      { Icon: ListChecks, text: "What courses are in year 2 of CS?" },
      { Icon: Briefcase, text: "Careers after Animation & VFX?" },
    ],
  },
  es: {
    eyebrow: "Tutor del Wiki de La Salle",
    h: "Pregunta sobre cualquier programa, curso o salida profesional.",
    sub:
      "Basado en el catálogo de salleurl.edu. El tutor cita páginas reales y te deriva a admisiones para precios.",
    starters: [
      { Icon: Compass, text: "Me interesa la tecnología — ¿qué puedo estudiar?" },
      { Icon: GitCompareArrows, text: "Compara los grados de Informática e IA" },
      { Icon: ListChecks, text: "¿Qué asignaturas hay en 2º de Informática?" },
      { Icon: Briefcase, text: "Salidas tras Animación y VFX" },
    ],
  },
};

export function EmptyState({ lang, onPick }: EmptyStateProps) {
  const copy = COPY[lang];
  return (
    <div className="empty">
      {/* Hero band — uses the campaign image but cropped tight, dimmed,
          and the script tagline overlaid. Disappears the moment the user
          sends their first message (per the design system's rule that
          marketing imagery never lives inside the chat itself). */}
      <div className="empty-hero" style={{ backgroundImage: `url(${heroImage})` }}>
        <div className="empty-hero-overlay" aria-hidden="true" />
        <div className="empty-hero-mark" aria-hidden="true">LS</div>
        <div className="empty-hero-tagline" aria-hidden="true">
          Be real,<br />be you.
        </div>
      </div>

      <div className="empty-eyebrow">{copy.eyebrow}</div>
      <h1 className="empty-h">{copy.h}</h1>
      <p className="empty-sub">{copy.sub}</p>
      <div className="starter-grid">
        {copy.starters.map(({ Icon, text }) => (
          <button key={text} className="starter" onClick={() => onPick(text)}>
            <Icon className="ico" />
            <span>{text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
