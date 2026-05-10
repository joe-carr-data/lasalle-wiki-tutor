# Wiki Tutor — UI Kit

The conversational chat interface for prospective and current La Salle Campus Barcelona students. Single-agent, streamed over SSE, bilingual EN/ES.

## What's here

- `index.html` — interactive click-thru demo. Pick a starter prompt or type your own; the agent fakes its own SSE stream so the timeline pulses, citations land, and program cards render.
- `components.jsx` — `Sidebar`, `TopBar`, `ChatMessage`, `AgentTimeline`, `ProgramCard`, `Composer`, `EmptyState`, `CitationChip`, `Avatar`.
- `app.jsx` — the demo orchestrator + scripted responses for ~6 questions plus a generic fallback.
- `styles.css` — UI kit styles. Imports the root `colors_and_type.css` for tokens.

## Visual rules specific to this kit

- **Two-column shell.** Left rail (280px, bone surface) holds brand mark, "New chat", conversation list, EN/ES toggle. Main column is paper.
- **Agent voice = brand.** User bubbles are `--brand-600`; agent bubbles are paper with a 1px line and a subtle shadow. Never invert.
- **Timeline above the answer.** The `thinking → tool → done` strip renders *above* the agent bubble. Active step has a brand-blue pulsing dot and a soft brand halo.
- **Citations live below.** Inline mono chips (`en/bachelor-artificial-intelligence`) — never linked text in the prose.
- **Program cards** are referenced inline when an answer leans on a specific program. Same shape as the search-result card preview.
- **Composer** uses the brand-blue circular send (arrow-up). Disabled state collapses to line-strong grey. Below it: pill suggestions. Above it: focused = brand ring (3px halo).

## What's intentionally not built

- Real auth, settings, share modals, file upload, or voice input. Stubbed with icons.
- Real markdown rendering in answer bodies — answers in the demo are plain text.
- The "thinking" state never errors; in production the SSE stream would emit `tool_error` and `cancelled` events the timeline must render too.
