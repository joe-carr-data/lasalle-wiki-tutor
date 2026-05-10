# La Salle Wiki Tutor — Design System

A design system for the **LaSalle Wiki Tutor**, an AI study advisor for prospective and current students of **La Salle Campus Barcelona** (Universitat Ramon Llull). It grounds every answer in the catalog of ~357 program pages and ~4,600 subject pages, streams reasoning + tool calls + answers over SSE, and answers in EN or ES.

This system houses the visual + interaction language for two surfaces:

1. **Wiki Tutor chat app** — the conversational interface where students ask questions and watch the agent search, fetch, and cite catalog entries.
2. **Catalog / Program pages** — high-fidelity references for the underlying salleurl.edu pages the tutor cites, so chat answers and deep-link previews feel of-a-piece.

## Sources used

- **Brand reference (visual)** — provided uploads:
  - `uploads/La_Salle_BCN_idLLGUjyO0_2.jpeg` — LSBCN square avatar (sky-blue `#5BA8DA`, white "LS", dark-ink "BCN")
  - `uploads/La_Salle_BCN_id7zea0aSU_1.png` — *LaSalle / Ramon Llull University* serif wordmark (black on white)
  - `uploads/La_Salle_BCN_id-5D9yGAl_0.jpeg` — "Be Real, Be You" campaign photo (immersive room, white hand-script tagline)
- **Public sites** referenced for tone, IA, and brand facts: `salleurl.edu/en`, `salleurl.edu/es`, `blogs.salleurl.edu`, La Salle Technova brand-refresh post (sky-blue alignment with campus identity).
- **Product spec** — supplied product brief covering the Wiki Tutor agent, its tool vocabulary, six personas, SSE event timeline, and bilingual catalog scope.
- No codebase or Figma was attached — recreations are based on the public site + brief.

## Index

| File / folder | What it is |
| --- | --- |
| `colors_and_type.css` | All design tokens: color scale, semantic vars, type scale, spacing, radii, shadows, motion. Import this in every artifact. |
| `assets/` | Logos and brand imagery (wordmark, LSBCN mark, "Be Real, Be You" hero). |
| `fonts/` | Webfont notes — we use Google Fonts substitutes (see "Font substitutions" below). |
| `preview/` | Card-sized HTML specimens registered to the Design System tab (one concept per card). |
| `ui_kits/wiki-tutor/` | Chat UI kit — JSX components + an interactive `index.html` demo. |
| `ui_kits/catalog/` | Program / subject page kit — JSX components + `index.html`. |
| `SKILL.md` | Agent-skill manifest so this folder works as a Claude skill. |

## Visual identity in one paragraph

La Salle BCN reads as **calm, blue, classical-but-modern**: a serif wordmark with deep ink, a confident sky-blue primary, generous white space, and the occasional handwritten "Be Real, Be You" mark layered onto immersive photography. The Wiki Tutor extends that into a chat interface — paper-white shell, blue brand accents reserved for the agent's voice, serif for headings and program titles, sans for UI, and citations rendered as small chips that link back to canonical catalog ids.

---

## CONTENT FUNDAMENTALS

The Wiki Tutor is grounded, bilingual, and student-first.

### Voice
- **Helpful peer + librarian.** Direct, factual, never marketing-y. The agent is a study advisor, not a recruiter — it does not sell programs.
- **Grounded over fluent.** If the catalog doesn't have it, the tutor says so plainly and points to the admissions office (`/en/admissions` / `/es/admisiones`). It never fabricates ECTS, durations, faculty, or course lists.
- **Bilingual mirror.** The tutor detects the student's language and answers in it. EN copy is plain-English Anglo-academic; ES copy uses *tú* (informal) — La Salle's marketing site addresses prospective students with *tú* / *vosotros* (e.g. *"Queremos que seáis auténticos, reales y vosotros mismos"*).
- **You / tú, never "we" for the institution.** When referring to La Salle the tutor says "La Salle" or "the program," not "we." It speaks *about* the university, not *as* it.

### Tone
- Warm but compact. Answers are short by default; the agent expands when asked.
- Confident about facts the catalog supports. Hedged ("I don't have that — admissions can confirm") about anything else.
- No emoji in answers. No exclamation marks. No emoji-bullets.
- Title Case for program names exactly as the catalog spells them (e.g. *"Bachelor's Degree in Animation & VFX"*).

### Casing & punctuation
- Sentence case for UI labels and section headings (*Syllabus*, *Career opportunities*).
- Program names retain their canonical casing.
- Acronyms uppercased: ECTS, AI, VFX, ICT, URL.
- Em-dashes spaced — like this — in EN copy. ES uses long dashes only in dialogue.

### Specific patterns
- **Citations** are inline chips with the canonical id, e.g. `en/bachelor-animation-and-vfx`. Click expands a peek; long-press copies.
- **"I don't know" pattern:** *"The catalog doesn't list tuition for that program. The admissions office handles pricing — you can reach them at /en/admissions."*
- **Comparisons** use a 2-column table with rows fixed at: Title · Level · Modality · Duration · ECTS · Languages · Start.
- **Lists** prefer bulleted prose over walls of text. Year-by-year curricula use a grouped list ("Year 1", "Year 2"…), never a giant table.

### Example answers (write copy in this voice)

> **Q.** Is the AI bachelor in English?
> **A.** Yes — the Bachelor's Degree in Artificial Intelligence is taught in English. It's a 4-year, 240 ECTS on-site program in Barcelona, starting in September. `en/bachelor-artificial-intelligence`

> **Q.** What's the difference between the CS and AI bachelors?
> **A.** Both are 4 years, 240 ECTS, on-site in Barcelona, taught in English. The CS bachelor goes broader across software engineering, systems and theory; the AI bachelor specialises earlier in machine learning, data and applied AI. Curriculum overlap is heaviest in years 1–2.
> Sources: `en/bachelor-computer-engineering`, `en/bachelor-artificial-intelligence`.

> **Q.** ¿Cuánto cuesta el máster en ciberseguridad?
> **A.** El catálogo no publica precios. Para matrícula y becas, contacta con admisiones en `/es/admisiones`.

---

## VISUAL FOUNDATIONS

### Color
Primary palette is **sky blue** (anchored at `#5BA8DA` from the LSBCN avatar) with a deep ink (`#111827`) for type and a warm bone (`#f7f6f2`) for secondary surfaces. We use a 9-stop tonal scale of the brand blue plus three neutrals (paper / mist / bone). Accents — cyan, amber, magenta — appear sparingly: cyan for Technova-adjacent surfaces, amber for soft CTAs / highlights, magenta only in tagline / campaign moments.

### Type
- **Serif** for headlines, the wordmark feel, and program titles — *Source Serif 4* (substitute for the bespoke wordmark face).
- **Sans** for UI, body, chat — *Source Sans 3* (substitute for La Salle's marketing sans).
- **Mono** for catalog ids, program codes, ECTS counts in tables — *JetBrains Mono*.
- **Script** for the "Be Real, Be You" tagline only — *Caveat* (substitute for the hand-lettered campaign mark). **Never** use script for body copy or UI.

### Spacing & layout
- 4px base grid. Generous gutters (24–48px on desktop). Content max-width 720–820px for chat, 1140px for catalog.
- Cards lean **square-ish with soft 14–20px corners**, not pill-rounded.
- The chat shell is left-aligned with a fixed left rail; the program page is centered on a wide column with a sticky right rail of facts.

### Backgrounds
- **No gradients** in product surfaces. Marketing imagery only.
- Photos are full-bleed with a subtle dark overlay so the white serif and script tagline stay legible.
- App surfaces are flat: paper or mist. Never patterned.

### Borders, radii, shadows
- 1px hairlines `var(--line)` everywhere; cards rarely need a stronger border.
- Radii: 6px (chips, inputs), 10px (buttons), 14px (cards), 20px (modals, hero panels).
- Shadow system is **two-layer, soft, and short-cast** — no heavy drop shadows. Brand shadow (blue-tinted) is reserved for the active-tool / agent-thinking pulse.

### Animation
- **Calm.** Easing `cubic-bezier(.22,.61,.36,1)`; durations 120ms (micro), 200ms (panels), 320ms (large surfaces).
- The agent's "thinking" pulse is the showpiece: a soft blue 1200ms loop on the active step in the timeline.
- Tokens stream in plain, no typewriter overshoot. Citations fade-and-rise 8px on append.

### Hover / press / focus
- **Hover** — links shift to `--brand-700`; cards lift `translateY(-1px)` + add `var(--shadow-2)`; primary buttons darken one step.
- **Press** — `transform: scale(0.98)`; press color is one step deeper than hover.
- **Focus** — visible ring `var(--ring-brand)` (3px brand-blue 32% halo). Never rely on color alone.

### Transparency & blur
- Reserved for the citation popover and the "agent thinking" toast — `rgba(255,255,255,.85)` with `backdrop-filter: blur(12px)`. Everything else is opaque.

### Imagery
- **Cool, contemporary, slightly under-saturated.** The "Be Real, Be You" hero is the warmest the system gets — used on marketing surfaces, never inside the chat.
- Faces and hand-script overlays are a recurring motif. No corporate stock.
- B&W is fine for archival / faculty headshots; full-bleed color for campaign hero.

### Iconography (also see ICONOGRAPHY below)
- Stroke-based, 1.5px, rounded caps. Paired with the sans typography. We use **Lucide** as the substitute system.

---

## ICONOGRAPHY

The salleurl.edu marketing site uses a stroke-based icon set with rounded terminals — typical of contemporary university sites. We do **not** have access to a bespoke La Salle icon font, so the design system substitutes:

- **[Lucide](https://lucide.dev/) (CDN)** — chosen because the stroke weight (1.5–2px), rounded line caps, and geometric construction match what we see on the public site. Loaded from `https://unpkg.com/lucide@latest`.
- **No emoji.** The Wiki Tutor never uses emoji in answers, in citations, or in UI. Some marketing TikTok/Insta surfaces use emoji freely, but those are out of scope for this system.
- **No unicode-character icons.** Avoid `→`, `✓`, `★` as decorative chrome — use Lucide equivalents (`arrow-right`, `check`, `star`) so weight and color stay consistent.
- **Logos** live in `assets/`: the *LaSalle / Ramon Llull University* wordmark (PNG; ideally swap for SVG when supplied) and the *LSBCN* sky-blue mark (raster avatar; an SVG version should replace this).
- **Program-area glyphs** — when a program needs a category icon (AI, Architecture, Business, Animation, etc.) we use a Lucide glyph mapped 1:1 to the area:
  - AI & Data Science — `brain-circuit`
  - Cybersecurity — `shield`
  - Animation & Digital Arts — `clapperboard`
  - Architecture — `building`
  - Business & Management — `briefcase`
  - Computer Science — `code`
  - Telecom & Electronics — `radio-tower`
  - Health Engineering — `heart-pulse`
  - Philosophy & Humanities — `book-open`
  - Project Management — `clipboard-list`

### Font substitutions — flagged for the user
The wordmark and marketing copy use bespoke / paid faces we don't have files for. Substitutions in this system, in priority order to replace with real assets:

1. **Wordmark serif** → *Source Serif 4* (Google Fonts). The real wordmark on the LaSalle / URL lockup is a custom-cut serif; please supply the licensed file if available.
2. **UI / body sans** → *Source Sans 3*. Salleurl.edu uses a humanist sans; supply if you have the campus-licensed file.
3. **"Be Real, Be You" hand-script** → *Caveat*. The campaign script is hand-lettered; if a vector exists, drop it as `assets/be-real-be-you-tagline.svg` and we'll wire it up in place of the Caveat fallback.
4. **Mono** → *JetBrains Mono*. Acceptable as-is.

---

*Continue to `colors_and_type.css` for tokens, `preview/` for card specimens, and `ui_kits/` for component recreations.*
