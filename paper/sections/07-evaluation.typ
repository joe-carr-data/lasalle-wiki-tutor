= Evaluation

We report five measurements. Each is reproducible from the scripts in `paper/scripts/`, with raw data dumps in `paper/data/`. Numbers are computed directly from primary sources -- catalog JSONL files, MongoDB collections, the live SSE endpoint -- and not from build-summary documents.

== Corpus coverage and frontmatter completeness

The corpus consists of 357 programs (179 EN, 178 ES) and 4{,}606 subjects (2{,}314 EN, 2{,}292 ES), counted from `wiki/meta/catalog.jsonl` and `wiki/meta/subjects.jsonl`. @fig:corpus shows the area distribution of the English catalog (panel a) and the frontmatter fields with the lowest completeness (panel b). The area distribution is heavy at Business & Management, Architecture, and AI & Data Science, with a long tail through Cybersecurity and Health Engineering. Eighteen frontmatter fields are present in 100% of records; ECTS clears 95% and `subject_count` 86%; the lowest-completeness fields are `degree_issuer` at 49.9% and the pairing fields at 57.7% (which is, by construction, the same population as the auto-linked pairs). All retrieval-critical fields used by the BM25-F scorer are at 100%.

#figure(image("../figures/fig09_corpus_coverage.pdf", width: 100%),
  caption: [Corpus coverage. (a) Programs by area in the EN catalog. (b) Frontmatter fields ranked by completeness, lowest first. Green is #math.gt.eq 95%, blue is 70--95%, orange below 70%.],
) <fig:corpus>

The pairing decomposition is the most informative coverage diagnostic. Of the 103 auto-linked EN--ES pairs, 36% were captured by the shared-subjects-plus-structural rule, 33% by the title-plus-slug rule, 22% by the weighted-score threshold, and 9% by the title-plus-structural rule (@fig:pairing, panel a). Panel b breaks the same 103 pairs into score bands: 27 are high-confidence (#math.gt.eq 0.70), 30 mid (0.50--0.70), and 46 low (0.30--0.50). The low-confidence band is the reason the OR-rules exist. Almost half of the auto-linked pairs are correctly identified by an OR-rule despite their weighted score being below 0.50; a single-threshold matcher with the same 0.5 cut would miss them.

#figure(image("../figures/fig13_pairing.pdf", width: 100%),
  caption: [Pairing decomposition. (a) Which OR-rule caught each auto-linked pair. (b) Weighted-score band among auto-linked pairs; 45% sit below 0.50 and would have been missed by a single-threshold matcher.],
) <fig:pairing>

@fig:unlinked breaks the linked-versus-unlinked count by level, computed against the English-side counts as the denominator. The bachelors line is essentially complete (1 of 29 English bachelors unlinked); the masters tail has 11 of 38 English masters unlinked; the bulk of the unlinked population sits in specialisations (28 of 49) and the "other" bucket (27 of 36), which matches the institutional reality that short-format and single-discipline offerings are commonly published in one language only. We do not claim that the matcher is correct on the unlinked programs in the sense that they would benefit from a manual review; we claim that the unlinked population is concentrated in the corpus segments where unpairedness is plausible by inspection of the institution's published catalog.

#figure(image("../figures/fig14_unlinked_breakdown.pdf", width: 100%),
  caption: [Linked and unlinked EN programs by level. Major degrees (bachelor, master) are well covered; the unlinked tail clusters in specialisations, "other" short-format programs, and online courses.],
) <fig:unlinked>

== Retrieval ablation across ranker modes

The ablation runs `paper/scripts/eval_ranker_ablation.py` four times against a 20-query benchmark (the 15-query failure suite from `tests/test_search_failure_benchmark.py` plus five bilingual extension queries that stress cross-lingual matching). For each ranker mode we record whether any expected substring appears in the top-1, top-3, and top-5 results, and we record the per-query retrieval latency.

#figure(image("../figures/fig10_ablation.pdf", width: 100%),
  caption: [Top-k hit rate by ranker mode on a 20-query benchmark. The hybrid blend reaches 100% top-5; lexical wins top-1 by five points; token-overlap, the legacy baseline, is dominated.],
) <fig:ablation>

@fig:ablation shows the headline result. The hybrid blend is the only mode that reaches 100% top-5 coverage. The lexical-only mode wins top-1 (85% versus the hybrid's 80%) and ties at top-3, but plateaus at top-5 (90%) because BM25-F has no recourse when the query and the program share zero literal tokens. The semantic-only mode is competitive at top-5 (95%) but loses ground at top-1 (70%); pool-normalisation on a small candidate set tends to give the cosine signal too much room to spread. The token-overlap legacy baseline, kept as a regression guard against the original failure that motivated the upgrade, reaches only 45% at every cut-off because it returns zero results on synonym and cross-lingual queries. The picture is consistent with the literature on the complementarity of lexical and dense signals @robertson2009bm25 @reimers2019sbert @karpukhin2020dpr. Median retrieval latency across all four modes is sub-millisecond once the BM25 index is warmed and the embedding matrix is loaded, which is why we use `search_programs` freely from inside the agent.

== Per-tool latency on the live deployment

Production latency comes from the `wiki_tutor_turn_traces` MongoDB collection on the live deploy, extracted via SSM and `paper/scripts/eval_latency_from_traces.py`. The collection at the time of writing contains 18 turn traces with 62 tool calls. @fig:latency shows a box plot of per-tool latency on a log-scale x-axis. The retrieval and detail tools cluster between 100 ms and 1 s. Two tools sit higher: `get_subject` shows a median around 3.9 s, which we attribute to the cumulative cost of loading the subject body, formatting the JSON return, and the agent-runtime overhead between `tool.start` and `tool.end` events; `search_programs` shows a long upper whisker because its first call per agent process pays the Model2Vec model-load and the BM25 index-build cost. Median latency for the cheap routing tools is in the hundreds of milliseconds; the agent's overall turn time is dominated by the LLM call to `gpt-5.4`, not by the tools.

#figure(image("../figures/fig11_latency.pdf", width: 100%),
  caption: [Per-tool latency on the live deployment, by tool name (log-scale x-axis). Boxes show median and quartiles, whiskers cover the typical range. Sample counts are annotated.],
) <fig:latency>

== Cost per turn and per conversation

Cost is computed from the token-usage metrics Agno records on each run in `wiki_tutor_agent_sessions`, multiplied by the published `gpt-5.4` on-demand rates. @fig:cost reports per-turn and per-conversation cost summary statistics. Median cost per turn is \$0.013; the p95 turn costs around \$0.06; the most expensive single turn observed in the trace store is \$0.08. Conversations skew shorter than turns suggest (median one turn per conversation), so the per-conversation median is \$0.006; the p95 is \$0.085 and the maximum is \$0.168. The total observed spend across all 38 turns is approximately \$0.77. Operationally, this means the variable cost of running the system is dominated by `gpt-5.4` tokens, not by retrieval infrastructure; the t3.micro that serves the system is fixed at approximately \$14 per month, and its CPU sees almost no load because all of the tools are file reads and a small static-embedding matrix multiplication. This is the empirical version of the design argument in Section 3: a 50 MB sidecar `.npz` plus a Python BM25 implementation is cheaper than the operational cost of a managed vector database for a corpus this size.

#figure(image("../figures/fig12_cost.pdf", width: 100%),
  caption: [Cost per turn and per conversation, in US dollars. Per-conversation median is low because many conversations are single-turn information requests; per-conversation tail tracks longer multi-turn explorations.],
) <fig:cost>

== Refusal correctness on the live deployment

Sixteen adversarial queries were run against the live SSE endpoint via `paper/scripts/eval_refusal_correctness.py`. The set spans seven categories: other-university comparisons (MIT, Stanford), general knowledge (capital of France, theory of relativity), coding help (Fibonacci, CSS centering), personal and immigration advice (Spanish student visa), scholarship routing (in-scope but requires "the catalog doesn't list pricing" response), prompt-override attempts (ignore previous instructions; act as a generic chatbot; print your system prompt), writing on the student's behalf (admission essay), and an in-scope control set in both English and Spanish. The agent declined every out-of-scope question with a one-to-two sentence response, in the user's language, offering the in-scope alternative. Representative verbatim refusals include "That's outside what I can help with -- I'm focused on LaSalle Campus Barcelona's catalog and programs" for an other-university comparison, "I can't ignore my role or switch to being a general chatbot" for a prompt-override, and "I can't share my system or hidden instructions" for an attempted system-prompt disclosure. The Spanish responses follow the same pattern with the same routing destinations (`/es/admisiones` for tuition and visa questions). The in-scope control queries returned full answers with multiple citations and one to two tool calls each. We do not claim refusal-rate guarantees on adversarial inputs at scale, only that on this hand-curated set the deployed system honoured its scope.
