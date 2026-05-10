// Typst paper template: two-column scientific article with proper title block,
// author affiliations, abstract, keywords, and figure/citation handling.
//
// Style is deliberately quiet — Computer Modern serif body, sans-serif for
// section headings, mono for code. No journal class-file dependency.

#let paper(
  title: none,
  authors: (),
  abstract: none,
  keywords: (),
  repo-url: none,
  live-url: none,
  bibliography: none,
  body,
) = {
  set document(title: title, author: authors.map(a => a.name).join(", "))
  set page(
    paper: "a4",
    // Side margins balance reading measure with figure width. ~16 cm
    // body fits the system architecture and SSE lifecycle diagrams
    // without clipping, while still keeping line length comfortable.
    margin: (top: 2.2cm, bottom: 2.2cm, left: 2.6cm, right: 2.6cm),
    numbering: "1",
    number-align: center,
  )
  set text(
    font: "New Computer Modern",
    size: 10.5pt,
    lang: "en",
  )
  set par(justify: true, leading: 0.65em, first-line-indent: 1.2em, spacing: 0.85em)

  // Section heading styling
  show heading: set text(font: "New Computer Modern", weight: "bold")
  show heading.where(level: 1): h => {
    set text(size: 12pt)
    block(above: 1.5em, below: 0.8em)[#counter(heading).display() #h.body]
  }
  show heading.where(level: 2): h => {
    set text(size: 11pt)
    block(above: 1.1em, below: 0.6em)[#counter(heading).display() #h.body]
  }
  show heading.where(level: 3): h => {
    set text(size: 10pt, style: "italic")
    block(above: 0.9em, below: 0.4em)[#h.body]
  }
  set heading(numbering: "1.1")

  // Figures: add breathing room above and below so captions don't
  // crash into the surrounding paragraphs.
  set figure(gap: 0.9em)
  show figure: it => {
    v(0.8em)
    it
    v(1.0em)
  }
  show figure.caption: c => {
    set text(size: 9pt)
    pad(x: 0.5em)[#text(weight: "bold")[Figure #c.counter.display(c.numbering).] #c.body]
  }

  // Code styling
  show raw.where(block: false): r => box(
    fill: rgb("#f5f5f5"),
    inset: (x: 3pt, y: 0pt),
    outset: (y: 3pt),
    radius: 2pt,
    text(font: "DejaVu Sans Mono", size: 0.92em)[#r],
  )
  show raw.where(block: true): r => block(
    fill: rgb("#f8f8f8"),
    inset: 8pt,
    radius: 3pt,
    width: 100%,
    text(font: "DejaVu Sans Mono", size: 0.88em)[#r],
  )

  // Title block (single-column, centered)
  align(center)[
    #block(width: 100%)[
      #text(size: 16pt, weight: "bold", font: "New Computer Modern")[#title]
    ]
    #v(0.6em)
    #block(width: 100%)[
      #for (i, a) in authors.enumerate() {
        if i > 0 [#h(0.8em)·#h(0.8em)]
        text(weight: "semibold")[#a.name]
        if a.at("note", default: none) != none [#super[\*]]
      }
    ]
    #v(0.2em)
    #block(width: 100%)[
      #set text(size: 9pt)
      #for (i, a) in authors.enumerate() {
        if a.email != none {
          if i > 0 [#h(0.8em)·#h(0.8em)]
          link("mailto:" + a.email)[#a.email]
        }
      }
    ]
    #if live-url != none or repo-url != none [
      #v(0.3em)
      #block(width: 100%)[
        #set text(size: 9pt)
        #if live-url != none [Live demo: #link(live-url)[#live-url]]
        #if live-url != none and repo-url != none [#h(0.6em)·#h(0.6em)]
        #if repo-url != none [Source: #link(repo-url)[#repo-url]]
      ]
    ]
  ]

  v(0.8em)

  // Abstract block (full-width)
  if abstract != none {
    block(
      width: 100%,
      inset: (x: 1.0cm, y: 0.4cm),
      [
        #align(center)[#text(font: "New Computer Modern", weight: "bold", size: 9.5pt)[Abstract]]
        #v(-0.3em)
        #set text(size: 9.5pt)
        #set par(justify: true, first-line-indent: 0pt)
        #abstract
      ],
    )
    if keywords.len() > 0 {
      block(
        width: 100%,
        inset: (x: 1.0cm),
        [
          #set text(size: 9pt)
          #set par(first-line-indent: 0pt)
          #text(weight: "bold")[Keywords—] #keywords.join("; ")
        ],
      )
    }
  }

  // Title-page note. Inline (not floated) so it never collides with the
  // body. Sits just below the keywords, before the body text begins.
  for a in authors {
    if a.at("note", default: none) != none {
      block(
        width: 100%,
        inset: (x: 1.0cm, y: 0.2cm),
        text(size: 8pt, fill: rgb("#4B5563"))[#emph[#super[\*] #a.note]],
      )
    }
  }

  v(0.6em)

  // Single-column body. The figures (especially the fletcher diagrams)
  // need the full text width to breathe. The line length is constrained
  // by generous side margins set above.
  body

  if bibliography != none {
    bibliography
  }
}

// Helper: title page (currently inlined above; kept here for future use).
#let title-page() = ()
