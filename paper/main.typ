// LaSalle Wiki Tutor — scientific article
// Authors: Alex Carreras Forns, Josep Carreras Molins, Claude Code
//
// Build:
//   typst compile paper/main.typ paper/main.pdf
// Watch:
//   typst watch paper/main.typ

#import "template.typ": paper, title-page

#show: paper.with(
  title: [#text(font: "New Computer Modern", weight: "bold")[An LLM Wiki for Higher Education]: Deterministic Catalog Tools with Selective Hybrid Retrieval for a Bilingual University Advisor],
  authors: (
    (
      name: "Alex Carreras Forns",
      email: "alexcarrerasforns@gmail.com",
      note: [Corresponding author. This work was prepared in support of the first author's application to LaSalle Campus Barcelona's Bachelor in Artificial Intelligence and Data Science.],
    ),
    (name: "Josep Carreras Molins", email: "joe.carr.data@gmail.com"),
    (name: "Claude Code", email: none),
  ),
  abstract: include "sections/02-abstract.typ",
  keywords: ("LLM agents", "tool use", "retrieval-augmented generation", "BM25", "static embeddings", "university advising", "observability", "system demonstration"),
  repo-url: "https://github.com/joe-carr-data/lasalle-wiki-tutor",
  live-url: "https://lasalle.generateeve.com",
  bibliography: bibliography("refs.bib", style: "ieee"),
)

#include "sections/03-introduction.typ"
#include "sections/04-related-work.typ"
#include "sections/05-system.typ"
#include "sections/06-deployment.typ"
#include "sections/07-evaluation.typ"
#include "sections/08-discussion.typ"
#include "sections/09-conclusion.typ"
#include "sections/11-acknowledgements.typ"
