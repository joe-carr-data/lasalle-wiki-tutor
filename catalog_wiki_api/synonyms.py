"""EN+ES synonym map for query normalization.

Maps student-facing vocabulary to the catalog's controlled vocabulary so
that lexical search (BM25) hits even when the student doesn't use the
exact title-keywords. Applied at query time, not index time.

Each rule maps a synonym (or short phrase) to one or more *expansion*
tokens that get added to the query (the original tokens are kept too —
expansion is additive, not replacement).

Lowercase. Order doesn't matter. Multi-word keys are matched as phrases.
"""

from __future__ import annotations

import re

# Phrase rules: full phrase → list of canonical tokens to add.
# Phrase keys must be matched as whole words/multi-word phrases first
# so "machine learning" doesn't get split into "machine" + "learning"
# and lose the AI association.
PHRASE_SYNONYMS: dict[str, list[str]] = {
    # AI / ML / data
    "machine learning": ["artificial", "intelligence", "ai"],
    "deep learning": ["artificial", "intelligence", "ai", "neural"],
    "ml": ["artificial", "intelligence", "ai"],
    "neural networks": ["artificial", "intelligence", "ai"],
    "natural language": ["artificial", "intelligence", "nlp"],
    "computer vision": ["artificial", "intelligence", "vision"],
    "data analysis": ["data", "science", "analytics"],
    "data analyst": ["data", "science", "analytics"],
    "data analytics": ["data", "science", "analytics"],
    "big data": ["data", "science", "analytics"],
    "aprendizaje automático": ["artificial", "intelligence", "ai", "inteligencia"],
    "aprendizaje profundo": ["artificial", "intelligence", "ai", "neural"],
    "redes neuronales": ["artificial", "intelligence", "ai"],
    "ciencia de datos": ["data", "science", "analytics"],
    "análisis de datos": ["data", "science", "analytics"],
    "inteligencia artificial": ["artificial", "intelligence", "ai"],

    # Cybersecurity
    "hacking": ["cybersecurity", "security"],
    "ethical hacking": ["cybersecurity", "security"],
    "info sec": ["cybersecurity", "security"],
    "infosec": ["cybersecurity", "security"],
    "cyber sec": ["cybersecurity", "security"],
    "cyber security": ["cybersecurity", "security"],
    "network security": ["cybersecurity", "security", "networks"],
    "seguridad informática": ["cybersecurity", "security"],
    "ciberseguridad": ["cybersecurity", "security"],

    # Software / programming
    "coding": ["programming", "software", "development"],
    "software engineering": ["programming", "software", "engineering"],
    "web development": ["programming", "web", "development"],
    "web dev": ["programming", "web", "development"],
    "back end": ["programming", "software", "backend"],
    "front end": ["programming", "software", "frontend"],
    "full stack": ["programming", "software", "fullstack"],
    "mobile development": ["programming", "mobile", "development"],
    "app development": ["programming", "mobile", "development"],
    "desarrollo software": ["programming", "software", "development"],
    "desarrollo web": ["programming", "web", "development"],
    "desarrollo móvil": ["programming", "mobile", "development"],

    # Business / entrepreneurship
    "startup": ["entrepreneurship", "business", "innovation"],
    "start-up": ["entrepreneurship", "business", "innovation"],
    "start up": ["entrepreneurship", "business", "innovation"],
    "founder": ["entrepreneurship", "business", "leadership"],
    "ceo training": ["leadership", "executive", "management"],
    "running a business": ["entrepreneurship", "business", "management"],
    "emprendimiento": ["entrepreneurship", "business", "innovation"],
    "emprendedor": ["entrepreneurship", "business"],
    "dirección de empresas": ["business", "management", "leadership"],

    # Animation / games / digital arts
    "video games": ["videogames", "animation", "multimedia"],
    "video game": ["videogames", "animation", "multimedia"],
    "videogame": ["videogames", "animation", "multimedia"],
    "videogames": ["videogames", "animation", "multimedia"],
    "game development": ["videogames", "animation", "multimedia", "programming"],
    "game design": ["videogames", "animation", "design", "multimedia"],
    "gaming": ["videogames", "animation", "multimedia"],
    "3d modelling": ["3d", "animation", "vfx"],
    "3d modeling": ["3d", "animation", "vfx"],
    "animation": ["animation", "vfx", "digital", "arts"],
    "visual effects": ["vfx", "animation"],
    "videojuegos": ["videogames", "animation", "multimedia"],
    "diseño de videojuegos": ["videogames", "animation", "design"],
    "animación digital": ["animation", "vfx", "digital"],

    # UX / design
    "ux": ["user", "experience", "design"],
    "ui": ["user", "interface", "design"],
    "user experience": ["user", "experience", "design"],
    "user interface": ["user", "interface", "design"],
    "interaction design": ["user", "experience", "design", "interaction"],
    "experiencia de usuario": ["user", "experience", "design"],
    "diseño de interfaces": ["user", "interface", "design"],

    # Architecture / building
    "architecture": ["architecture", "building", "design"],
    "urban planning": ["architecture", "urban", "planning"],
    "interior design": ["architecture", "interior", "design"],
    "construction": ["building", "construction", "engineering"],
    "bim": ["building", "bim", "architecture"],
    "arquitectura": ["architecture", "building", "design"],
    "edificación": ["building", "construction"],
    "urbanismo": ["urban", "planning"],

    # Engineering family
    "robotics": ["robotics", "electronic", "engineering"],
    "iot": ["electronic", "engineering", "telematics"],
    "telecommunications": ["telecom", "telecommunications", "engineering"],
    "telemetry": ["telematics", "engineering"],
    "biomedical": ["health", "engineering", "biomedical"],
    "robótica": ["robotics", "electronic", "engineering"],
    "telecomunicaciones": ["telecom", "telecommunications", "engineering"],

    # Project management / business ops.
    # Note: bare "lean" used to be expanded to project/management which
    # over-matched against unrelated programs that mention "lean" loosely.
    # Tightened to phrase contexts (lean six sigma, lean project, lean
    # construction, lean management).
    "project management": ["project", "management"],
    "pmp": ["project", "management"],
    "scrum": ["project", "management", "agile"],
    "agile": ["project", "management", "agile"],
    "lean six sigma": ["project", "management", "lean", "six", "sigma"],
    "lean project": ["project", "management", "lean"],
    "lean construction": ["project", "management", "lean", "construction"],
    "lean management": ["project", "management", "lean"],
    "dirección de proyectos": ["project", "management"],
    "gestión de proyectos": ["project", "management"],

    # Philosophy / humanities.
    # Note: bare "thinking" expanded to thought/creativity/philosophy
    # caught technical phrases like "thinking about technology in business",
    # over-pulling philosophy programs. Tightened to phrase contexts only.
    "ethics": ["philosophy", "ethics"],
    "humanities": ["philosophy", "humanities"],
    "critical thinking": ["thought", "creativity", "philosophy"],
    "creative thinking": ["thought", "creativity"],
    "design thinking": ["thought", "creativity", "innovation"],
    "thinking and creativity": ["thought", "creativity", "philosophy"],
    "filosofía": ["philosophy", "humanities"],
    "ética": ["philosophy", "ethics"],

    # Generic level / format hints (boost matching programs)
    "long degree": ["bachelor", "degree"],
    "long program": ["bachelor", "degree", "master"],
    "short course": ["course", "specialization"],
    "weekend course": ["course", "executive"],
    "evening": ["executive", "part-time"],
    "remote": ["online"],
    "remoto": ["online"],
    "a distancia": ["online"],
    "presencial": ["on-site"],
}

# Single-word rules for cases not covered by phrase rules above.
# Useful when the user types one isolated token (e.g. "AI", "MBA").
TOKEN_SYNONYMS: dict[str, list[str]] = {
    "ai": ["artificial", "intelligence"],
    "ml": ["artificial", "intelligence"],
    "ux": ["user", "experience"],
    "ui": ["user", "interface"],
    "iot": ["electronic", "engineering"],
    "mba": ["business", "administration"],  # narrow — "mba" is already a strong term
    "phd": ["doctorate"],
    "msc": ["master"],
    "ms": ["master"],
    "ba": ["bachelor"],
    "bsc": ["bachelor"],
    "ia": ["artificial", "intelligence"],  # ES abbreviation for AI
}


_PHRASE_PATTERNS = [
    (re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE), tokens)
    for phrase, tokens in PHRASE_SYNONYMS.items()
]


def expand_query(query: str) -> list[str]:
    """Return the original query tokens plus synonym-expansion tokens.

    The expansion is additive: original words are preserved so an exact-
    match still wins on rarer terms (high IDF in BM25).
    """
    if not query:
        return []
    lowered = query.lower()
    expansions: list[str] = []
    matched_phrases: list[tuple[int, int]] = []
    for pattern, extra in _PHRASE_PATTERNS:
        for m in pattern.finditer(lowered):
            expansions.extend(extra)
            matched_phrases.append((m.start(), m.end()))
    # Tokenize the original query (alphanumeric, ≥2 chars)
    base_tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]{2,}", lowered)
    # Apply per-token synonyms to base tokens that didn't get caught by phrases
    for t in base_tokens:
        if t in TOKEN_SYNONYMS:
            expansions.extend(TOKEN_SYNONYMS[t])
    return base_tokens + expansions
