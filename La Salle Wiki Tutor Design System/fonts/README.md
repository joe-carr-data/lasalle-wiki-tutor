# Fonts

This system uses Google Fonts substitutes loaded via CDN in `colors_and_type.css`.

Real La Salle BCN typefaces have not been supplied — see README's *Font substitutions* section.

| Token | Substitute | Replace with |
| --- | --- | --- |
| `--font-serif` | Source Serif 4 | Wordmark serif (licensed file) |
| `--font-sans` | Source Sans 3 | Marketing humanist sans |
| `--font-mono` | JetBrains Mono | OK as-is |
| `--font-script` | Caveat | "Be Real, Be You" hand-script (vector) |

Drop `.woff2` files here and update `colors_and_type.css` to swap the `@import` for `@font-face` rules.
