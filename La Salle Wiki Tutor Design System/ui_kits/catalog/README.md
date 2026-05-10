# Catalog UI Kit

A high-fidelity recreation of a **salleurl.edu program page** — the kind of page the Wiki Tutor cites and that prospective students land on after clicking through a chat answer.

## Files

- `index.html` — interactive demo. Top nav, hero, sticky fact rail, sub-page tabs (Overview · Goals · Syllabus · Methodology · Career), bilingual EN/ES toggle.
- `Header.jsx` — top navigation with the LaSalle wordmark, primary nav, and language switcher.
- `ProgramHero.jsx` — title, level/area eyebrow, photo with subtle dark overlay, "Apply" CTA.
- `FactRail.jsx` — sticky right-rail facts (Modality · Duration · ECTS · Languages · Start · Location).
- `SubPageTabs.jsx` — Overview / Goals / Requirements / Syllabus / Methodology / Faculty / Careers tab bar.
- `SyllabusYearList.jsx` — grouped year-by-year list of subjects (with ECTS badges).
- `Footer.jsx` — La Salle / URL lockup + admissions link.

## Scope and limits

- This kit is **cosmetic**. State, routing and real data are mocked.
- One sample program (*Bachelor's Degree in Artificial Intelligence*) is fully populated; the rest are stubs to demonstrate the layout.
- We didn't have the source codebase or Figma — pages are recreated from public salleurl.edu screenshots and tone, anchored to the `colors_and_type.css` tokens.
