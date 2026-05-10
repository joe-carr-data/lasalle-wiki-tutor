// Native Typst diagrams. All figures use `grid` + `box` for full
// control over alignment and sizing. No fletcher / cetz auto-layout.
// This is deliberate: fletcher's column auto-sizing produced uneven
// box widths and clipped subtitles on this document.

// ─── Palette ────────────────────────────────────────────────────────────
#let BLUE = rgb("#5BA8DA")
#let DARK = rgb("#205C87")
#let LIGHT = rgb("#D3E8F6")
#let ORANGE = rgb("#E89E48")
#let GREEN = rgb("#7CB07C")
#let PAPER = rgb("#FAF8F4")
#let GRAY = rgb("#9CA3AF")
#let INK = rgb("#111827")

// ─── Shared building blocks ─────────────────────────────────────────────
//
// `card` is a uniform box with title + optional subtitle. All diagrams
// use it so cards across figures look consistent.

#let card(
  title,
  sub: none,
  color: BLUE,
  fg: white,
  w: 6.5em,
  h: 4.2em,
) = box(
  fill: color,
  stroke: 0.7pt + DARK,
  radius: 4pt,
  inset: (x: 6pt, y: 7pt),
  width: w,
  height: h,
  align(center + horizon)[
    #text(fill: fg, weight: "bold", size: 8.5pt)[#title]
    #if sub != none [
      #v(-0.45em)
      #text(fill: fg, weight: "regular", size: 7pt)[#sub]
    ]
  ],
)

// Glyph arrows — used as standalone grid cells between cards. They sit
// vertically centered with the card row so the line of arrows is even.

#let h-arrow = align(center + horizon)[
  #text(size: 14pt, fill: GRAY, weight: "bold")[→]
]
#let h-arrow-bi = align(center + horizon)[
  #text(size: 14pt, fill: GRAY, weight: "bold")[↔]
]
#let v-arrow = align(center + horizon)[
  #text(size: 14pt, fill: GRAY, weight: "bold")[↓]
]
#let down-right = align(center + horizon)[
  #text(size: 14pt, fill: GRAY, weight: "bold")[↘]
]
#let up-right = align(center + horizon)[
  #text(size: 14pt, fill: GRAY, weight: "bold")[↗]
]

// Small italic caption for inline annotations under a card.
#let _annot(content) = text(size: 7pt, fill: GRAY, style: "italic", content)


// ═══════════════════════════════════════════════════════════════════════
// Figure 1 — Graphical abstract
// ═══════════════════════════════════════════════════════════════════════
//
// Five concept nodes laid out as: Question → Agent → (Wiki || Retrieval) → Answer.
// The middle column is two stacked cards (Wiki on top, Retrieval below)
// so the branching is visible without fancy edge geometry.

#let graphical-abstract = align(center)[
  #grid(
    columns: (auto, auto, auto, auto, auto),
    rows: (auto, 0.4em, auto),
    column-gutter: 0.5em,
    align: horizon,

    // Row A: question, arrow, top branch, arrow, answer
    card([Student \ question],
         sub: [#emph["¿qué grado en \ IA tenéis?"] (ES)],
         color: PAPER, fg: INK, w: 8em),
    h-arrow,
    grid(
      rows: (auto, 0.5em, auto),
      card([Compiled wiki],
           sub: [357 programs \ 4,606 subjects],
           color: GREEN, w: 9em, h: 3.8em),
      none,
      card([Hybrid retrieval],
           sub: [BM25-F ⊕ Model2Vec \ 0.55 / 0.45 blend],
           color: ORANGE, w: 9em, h: 3.8em),
    ),
    h-arrow,
    card([Answer + \ citation],
         sub: [Bachelor in AI \ [salleurl.edu]],
         color: PAPER, fg: INK, w: 8em),
  )
  #v(0.7em)
  #align(center, _annot[Through one streaming Agno + GPT-5.4 agent.])
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 2 — System architecture (5-stage horizontal pipeline)
// ═══════════════════════════════════════════════════════════════════════

#let system-arch = align(center)[
  #grid(
    columns: (auto,) * 9,
    column-gutter: 0.4em,
    align: horizon,
    card([Crawler], sub: [polite resumable \ fetcher]),
    h-arrow,
    card([Wiki render], sub: [structured \ Markdown]),
    h-arrow,
    card([Catalog API], sub: [10 read-only \ tools]),
    h-arrow,
    card([Streaming \ agent], sub: [Agno · GPT-5.4 \ over SSE]),
    h-arrow,
    card([React 19 \ client], sub: [served from \ FastAPI]),
  )
  #v(0.8em)
  #box(
    fill: GREEN,
    stroke: 0.7pt + DARK,
    radius: 4pt,
    inset: (x: 10pt, y: 8pt),
    width: 72%,
    align(center)[
      #text(fill: white, weight: "bold", size: 9pt)[MongoDB]
      #v(-0.4em)
      #text(fill: white, size: 7.5pt)[agent_sessions  ·  conversations_meta  ·  turn_traces]
    ],
  )
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 3 — Crawl-and-build pipeline
// ═══════════════════════════════════════════════════════════════════════
//
// Source → extractor → 2 outputs → pairing → final wiki. Six cards with
// a vertical branch in the middle.

#let crawl-pipeline = align(center)[
  #grid(
    columns: (auto, auto, auto, auto, auto, auto, auto, auto, auto),
    column-gutter: 0.4em,
    align: horizon,
    card([salleurl.edu], sub: [Drupal · no \ sitemap], color: PAPER, fg: INK, w: 6em, h: 4.6em),
    h-arrow,
    card([Field-targeted \ extractors],
         sub: [Drupal field-name \ selectors], w: 7em, h: 4.6em),
    h-arrow,
    // Middle column is two stacked artefacts
    grid(
      rows: (auto, 0.4em, auto),
      card(text(font: "DejaVu Sans Mono", size: 8pt)[structured.jsonl],
           color: LIGHT, fg: INK, w: 8em, h: 2em),
      none,
      card(text(font: "DejaVu Sans Mono", size: 8pt)[pairings.jsonl],
           color: LIGHT, fg: INK, w: 8em, h: 2em),
    ),
    h-arrow,
    card([Cross-language \ pairing],
         sub: [greedy bipartite \ multi-signal], color: ORANGE, w: 7.5em, h: 4.6em),
    h-arrow,
    card([wiki/], sub: [EN + ES \ Markdown tree], color: DARK, w: 5em, h: 4.6em),
  )
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 4 — Wiki on-disk layout + frontmatter schema (two-column)
// ═══════════════════════════════════════════════════════════════════════

#let wiki-layout = grid(
  columns: (1.1fr, 1fr),
  gutter: 1em,
  // Left: directory tree. Monospace alignment requires justify: false.
  block(
    fill: PAPER,
    stroke: 0.6pt + DARK,
    radius: 4pt,
    inset: 8pt,
    width: 100%,
    [
      #set text(font: "DejaVu Sans Mono", size: 7.5pt)
      #set par(first-line-indent: 0pt, leading: 0.55em, justify: false)
      #set align(left)
      `wiki/` \
      `├── INDEX.md, faq.md, glossary.md` \
      `├── meta/` \
      `│   ├── catalog.jsonl     `  #text(size: 6.5pt, fill: GRAY)[(357 program records)] \
      `│   ├── subjects.jsonl    `  #text(size: 6.5pt, fill: GRAY)[(4,606 subject records)] \
      `│   ├── pairings.jsonl    `  #text(size: 6.5pt, fill: GRAY)[(EN↔ES candidates)] \
      `│   ├── embeddings_en.npz `  #text(size: 6.5pt, fill: GRAY)[(Model2Vec 256-d)] \
      `│   └── embeddings_es.npz` \
      `├── en/` \
      `│   ├── INDEX.md, by-area/, by-level/` \
      `│   ├── programs/{slug}/` \
      `│   │   ├── README.md      `  #text(size: 6.5pt, fill: GRAY)[(frontmatter + overview)] \
      `│   │   ├── goals.md, requirements.md` \
      `│   │   ├── curriculum.md, careers.md` \
      `│   │   └── methodology.md, faculty.md` \
      `│   └── subjects/{slug}.md` \
      `└── es/   `                   #text(size: 6.5pt, fill: GRAY)[(mirrors en/, /estudios/ slug)]
    ],
  ),
  block(
    fill: LIGHT,
    stroke: 0.6pt + DARK,
    radius: 4pt,
    inset: 10pt,
    width: 100%,
    [
      #set align(center)
      #text(size: 9pt, weight: "bold", fill: DARK)[Program frontmatter schema]
      #v(0.3em)
      #set align(left)
      #set text(font: "DejaVu Sans Mono", size: 7.5pt)
      #set par(first-line-indent: 0pt, leading: 0.6em, justify: false)
      • `title`, `slug`, `canonical_program_id` \
      • `level`, `area`, `official`, `tags` \
      • `modality` (array), `duration`, `ects` \
      • `languages_of_instruction` (array) \
      • `schedule`, `location`, `start_date` \
      • `tuition_status`, `admissions_contact` \
      • `official_name`, `degree_issuer` \
      • `subject_count`, `related_programs` \
      • `equivalent_program_id` \
      • `pairing_confidence`, `pairing_method` \
      • `source_url`, `source_fetched_at` \
      • `extractor_version`, `extractor_mode` \
      • `last_built_at`
    ],
  ),
)


// ═══════════════════════════════════════════════════════════════════════
// Figure 5 — Ten-tool surface
// ═══════════════════════════════════════════════════════════════════════
//
// 4×2 grid of detail/browse tools + a centered pair of routing tools.
// We show the tools as a clean inventory; flows are described in the
// caption rather than overlaid as arrows (overlaid arrows on a 10-tool
// grid were impossible to read at column width).

#let _tool(name, color: BLUE) = box(
  fill: color,
  stroke: 0.7pt + DARK,
  radius: 4pt,
  inset: (x: 6pt, y: 8pt),
  width: 10em,
  height: 2.4em,
  align(center + horizon)[
    #text(font: "DejaVu Sans Mono", fill: white, weight: "bold", size: 9pt)[#name]
  ],
)

#let tool-surface = align(center)[
  #grid(
    columns: (auto, auto, auto, auto),
    column-gutter: 0.5em,
    row-gutter: 0.5em,
    _tool("search_programs"),    _tool("list_programs"),
    _tool("get_index_facets"),   _tool("compare_programs"),

    _tool("get_program"),        _tool("get_program_section"),
    _tool("get_curriculum"),     _tool("get_subject"),
  )
  #v(0.4em)
  #grid(
    columns: (auto, auto),
    column-gutter: 0.5em,
    _tool("get_faq", color: GREEN),
    _tool("get_glossary_entry", color: GREEN),
  )
  #v(0.6em)
  #align(center, _annot[Blue: retrieval and detail tools. Green: routing tools (FAQ, glossary).])
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 6 — Hybrid retrieval inside search_programs
// ═══════════════════════════════════════════════════════════════════════
//
// Linear pipeline with a parallel branch: lexical (top) and semantic
// (bottom) run in parallel between synonym-expansion and the blend.

// Hybrid retrieval — single 2-row, 11-column grid. The "main line"
// cells (query, →, synonym, ⤳, blend, →, intent) span both rows so
// they sit centered vertically; the two branches (BM25-F, Model2Vec)
// and their pool-norms occupy individual rows. Arrows between branch
// cards are explicit, on the same row as the cards they connect, so
// every adjacency is unambiguous.

#let hybrid-retrieval = align(center)[
  #grid(
    columns: 11,
    column-gutter: 0.4em,
    row-gutter: 0.4em,
    align: horizon + center,

    // ── Row 0 (top branch: lexical) ─────────────────────────────────
    grid.cell(rowspan: 2, card([query], sub: [#emph["machine \ learning"]], color: PAPER, fg: INK, w: 6em, h: 9em)),
    grid.cell(rowspan: 2, h-arrow),
    grid.cell(rowspan: 2, card([synonym \ expansion], sub: [EN+ES table], w: 6.5em, h: 9em)),
    grid.cell(rowspan: 2, h-arrow),
    card([BM25-F], sub: [6 fields · IDF \ k1=1.5  b=0.75], color: DARK, w: 6.5em),
    h-arrow,
    card([pool-norm], sub: [scaled to [0,1] \ in top-K pool], color: LIGHT, fg: INK, w: 6em),
    grid.cell(rowspan: 2, h-arrow),
    grid.cell(rowspan: 2, card([blend], sub: [0.55·L \ + 0.45·S], color: ORANGE, w: 5em, h: 9em)),
    grid.cell(rowspan: 2, h-arrow),
    grid.cell(rowspan: 2, card([intent \ prior], w: 5em, h: 9em)),

    // ── Row 1 (bottom branch: semantic) ─────────────────────────────
    card([Model2Vec], sub: [potion-base-8M \ 256-d static], color: GREEN, w: 6.5em),
    h-arrow,
    card([pool-norm], sub: [cosine sim \ scaled to [0,1]], color: LIGHT, fg: INK, w: 6em),
  )
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 7 — SSE event lifecycle + Mongo fan-out
// ═══════════════════════════════════════════════════════════════════════
//
// Top row: linear streaming path. Below: parallel listener writing the
// trace store; a side connection from the agent itself to the session
// store. Built with one outer grid for the top row, then a second row
// below for the trace path.

#let sse-lifecycle = align(center)[
  // One unified 2-row, 9-column grid. Row 1 is the streaming hot path
  // (5 cards + 4 arrows = 9 cells). Row 2 sits the TurnTraceRecorder
  // exactly under BaseSSEAdapter (column 3 of the same grid), with a
  // down-arrow above it in row 1.5 — all in the same column system.
  //
  // The column widths are fixed so both rows align by construction.
  #grid(
    columns: (7em, 1.5em, 8.5em, 1.5em, 9em, 1.5em, 7em),
    column-gutter: 0pt,
    row-gutter: 0.4em,
    align: horizon + center,

    // Row 1 — hot path
    card([Streaming \ agent], sub: [Agno · GPT-5.4 \ Responses API], w: 7em),
    h-arrow,
    card([BaseSSEAdapter], sub: [AgentEvent → wire], w: 8.5em),
    h-arrow,
    card([SSE wire], sub: [session.* · thinking.* \ tool.* · final_response.*],
         color: PAPER, fg: INK, w: 9em),
    h-arrow,
    card([React client], sub: [Turn[] reducer \ live timeline], color: DARK, w: 7em),

    // Spacer row with down-arrow under BaseSSEAdapter
    none, none, v-arrow, none, none, none, none,

    // Row 2 — trace path. TurnTraceRecorder sits in column 3, the
    // arrow in column 4, and the trace collection card spans columns
    // 5-7 so it ends at the right edge of the React client above.
    none, none,
    card([TurnTraceRecorder], sub: [parallel listener, \ off the hot path],
         color: ORANGE, w: 8.5em),
    h-arrow,
    grid.cell(colspan: 3,
      card([wiki_tutor_turn_traces], sub: [one document per run_id],
           color: GREEN, w: 17.5em),
    ),
  )
  #v(0.6em)
  #align(center, _annot[Agno also persists `agent_sessions` directly to MongoDB (not shown).])
]


// ═══════════════════════════════════════════════════════════════════════
// Figure 8 — Deployment topology
// ═══════════════════════════════════════════════════════════════════════
//
// Row 1: in-host stack (Caddy → uvicorn ↔ Mongo) + SSM Session Manager
// to the right.
// Row 2: hardware strip (Elastic IP / EBS snapshots / IMDSv2).
// Row 3: Terraform provisioner pointing up at the strip.

#let deployment = align(center)[
  #grid(
    columns: (auto, auto, auto, auto, auto, auto, auto),
    column-gutter: 0.4em,
    align: horizon,
    card([Caddy], sub: [Let's Encrypt \ TLS · :80 :443], w: 6.5em),
    h-arrow,
    card([uvicorn], sub: [FastAPI under \ systemd], w: 6.5em),
    h-arrow-bi,
    card([Mongo], sub: [docker compose \ local volume], color: GREEN, w: 6.5em),
    h-arrow-bi,
    card([SSM Session \ Manager], sub: [no SSH \ no port 22], color: ORANGE, w: 7em),
  )
  #v(0.5em)
  #box(
    fill: DARK,
    stroke: 0.7pt + DARK,
    radius: 4pt,
    inset: (x: 10pt, y: 8pt),
    width: 90%,
    align(center)[
      #text(fill: white, size: 8.5pt, weight: "bold")[Elastic IP  ·  daily EBS snapshots  ·  IMDSv2 required]
    ],
  )
  #v(0.3em)
  #v-arrow
  #v(0.1em)
  #card([Terraform], sub: [provisions all the above], w: 12em, h: 3em)
]
