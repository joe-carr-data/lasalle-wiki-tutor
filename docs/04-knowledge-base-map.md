# 04 – Knowledge base map

Last updated: 2026-05-10

## What we have

```
                    ┌─────────────────────────────────────────┐
                    │          DOWNLOADED CORPUS              │
                    │          7,277 unique URLs              │
                    │          EN (3,638) + ES (3,639)        │
                    └─────────────┬───────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────────┐
          │                       │                           │
    ┌─────▼──────┐        ┌──────▼───────┐           ┌───────▼────────┐
    │  PROGRAMS  │        │  SUBJECTS    │           │  ANCILLARY     │
    │  357 bases │        │  (courses)   │           │  PDFs          │
    │  +2,136    │        │  4,606 pages │           │  177 files     │
    │  subpages  │        │              │           │                │
    └─────┬──────┘        └──────────────┘           └────────────────┘
          │
    ┌─────┴─────────────────────────────────────────┐
    │                                               │
    │  Program types (EN counts, ES mirrors):       │
    │  ┌──────────────────────┬──────┐              │
    │  │ Bachelors            │   30 │              │
    │  │ Masters              │   55 │              │
    │  │ Specialization       │   66 │              │
    │  │ Summer/workshops     │   23 │ ← "other"   │
    │  │ Online               │    4 │   + summer   │
    │  │ Doctorate            │    1 │              │
    │  └──────────────────────┴──────┘              │
    │                                               │
    │  Each program has up to 7 pages:              │
    │  ┌────────────────────────────────────┐       │
    │  │ base (overview/presentation)       │       │
    │  │ goals (learning outcomes)          │       │
    │  │ requirements (admission)           │       │
    │  │ syllabus (course list + links)     │       │
    │  │ methodology (teaching approach)    │       │
    │  │ academics (faculty)                │       │
    │  │ career-opportunities (roles)       │       │
    │  └────────────────────────────────────┘       │
    │  356/357 programs have all 6 subpages.        │
    └───────────────────────────────────────────────┘
```

## Student-relevant content (USE)

| Content | Source | What students care about | Volume |
|---------|--------|--------------------------|--------|
| **Program overview** | base page | What is this degree? Description, format, duration, language, price | 357 pages |
| **Goals / learning outcomes** | /goals or /objetivos | What will I learn? Skills and competencies | 356 pages |
| **Admission requirements** | /requirements or /requisitos | Can I get in? Prerequisites, pathways | 356 pages |
| **Syllabus / course list** | /syllabus or /plan-estudios | What courses will I take? Semester-by-semester plan | 356 pages |
| **Career opportunities** | /career-opportunities or /salidas-profesionales | What can I do after? Job roles, industries | 356 pages |
| **Subject details** | /en/{slug} or /es/{slug} | Course description, objectives, contents, evaluation, prerequisites, credits | 4,606 pages |
| **Program metadata** | base page structured fields | Modality (on-site/online/blended), duration, ECTS credits, language of instruction, official name, degree certificate issuer | embedded in base |

## Content of limited student value (DEPRIORITIZE)

| Content | Source | Why less useful | Volume |
|---------|--------|-----------------|--------|
| **Methodology** | /methodology or /metodologia | Teaching approach — generic across programs ("project-based learning", "seminars"). Low discrimination value for choosing a program. | 356 pages |
| **Academics / Faculty** | /academics or /profesorado | Professor names and bios. Rarely a deciding factor for students. Useful for advanced search but low priority. | 356 pages |
| **Ancillary PDFs** | /sites/default/files/... | Scholarship forms (44), credit convalidation guides (36), misc program docs (97). Administrative, not informational. | 177 files |
| **Non-program page** | 1 category page that slipped through | Not a program. | 1 page |

## Content structure inside each page type

### Program base page (the richest page)
```
article > div.content
  ├── div.view-tabs-estudis          → nav tabs (not content)
  ├── div.field-name-field-ent-nomoficial  → official degree name
  ├── div.field-name-field-tx-expedicio    → who issues the certificate
  ├── div.view-modalitats-eva        → TABLE: modality, duration, ECTS, language, places, price
  └── div.paragraphs-items           → rich text: description, collaborators, highlights
```

### Subject (course) page
```
article > div.content
  ├── div.field-ent-descripcio       → course description
  ├── div.group-assign-01            → type, semester, credits
  ├── div.field-ent-coneixementsprevis → prerequisites
  ├── div.field-ent-objectius        → learning objectives
  ├── div.field-ent-continguts       → syllabus / topics
  ├── div.field-ent-metodologia      → teaching method
  ├── div.field-ent-avaluacio        → assessment method
  ├── div.field-ent-criterisavaluacio → grading criteria
  └── div.field-ent-bibliografiabasica → reading list
```

## What's missing from the corpus

| Gap | Impact | Mitigation |
|-----|--------|------------|
| **Subject-to-program links are incomplete** | Only 76/179 EN programs have linked_subjects populated (the ones fetched in the initial run). Resume run populated subpages_present but not linked_subjects for already-done bases. | Can be rebuilt: scan manifest for subject records with `parent_url`, or re-parse syllabus HTML. |
| **No pricing data anywhere** | The site does not publish tuition/pricing on program pages. The modalities table has duration, credits, language, schedule, location — but no price field. Students are directed to contact admissions. | The AI assistant should acknowledge this gap and direct students to admissions. |
| **No structured metadata per subject** | Credits, semester, type (mandatory/elective) are in the HTML but not in the manifest. | Extract during Phase 3. |
| **EN/ES cross-linking** | We don't know which EN program corresponds to which ES program. | Could match by slug similarity or by shared subject URLs. |

## Recommended content tiers for the AI assistant

### Tier 1 — Index and retrieve (core)
- Program base pages (overview, description, modalities table)
- Goals / learning outcomes
- Requirements / admission
- Career opportunities
- Syllabus (course list per semester)
- Subject descriptions + objectives + prerequisites

### Tier 2 — Available but lower priority
- Methodology pages
- Faculty/academics pages
- Subject evaluation criteria and bibliography

### Tier 3 — Skip for now
- Ancillary PDFs (scholarship forms, convalidation guides)
- Non-program pages
- Nav/footer/sidebar boilerplate in HTML
