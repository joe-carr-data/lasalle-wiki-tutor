#!/usr/bin/env bash
# Package the local wiki/ corpus and upload it to a GitHub Release.
#
# Required: gh CLI authenticated against the repo's GitHub account.
#
# Usage:
#   scripts/publish_wiki.sh [TAG]
#
#   TAG    Release tag to create (or update). Defaults to "wiki-latest", a
#          rolling tag that always points at the most recent corpus build.
#          Use a versioned tag (e.g. wiki-2026-05-10) to pin a specific
#          snapshot.
#
# Behavior:
#   - Refuses to run if wiki/ is missing or has zero markdown files.
#   - Tars wiki/ to .cache/wiki.tar.gz.
#   - Creates the release if it doesn't exist; replaces the asset if it does.

set -euo pipefail

TAG="${1:-wiki-latest}"
ASSET="wiki.tar.gz"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d wiki ]]; then
  echo "ERR: wiki/ not found in $ROOT" >&2
  exit 2
fi
MD_COUNT=$(find wiki -name '*.md' | wc -l | tr -d ' ')
if [[ "$MD_COUNT" -lt 100 ]]; then
  echo "ERR: wiki/ only has $MD_COUNT markdown files — refusing to publish a partial corpus" >&2
  exit 2
fi
if [[ ! -f wiki/meta/embeddings_meta.json ]]; then
  echo "ERR: wiki/meta/embeddings_meta.json missing — run scripts/build_embeddings.py first" >&2
  exit 2
fi

mkdir -p .cache
TARBALL=".cache/$ASSET"
echo "→ Packing wiki/ ($MD_COUNT markdown files + sidecars) → $TARBALL"
# COPYFILE_DISABLE prevents macOS BSD tar from bundling AppleDouble
# sidecar files (._foo.md, ._foo/, etc.) alongside the real files. Those
# sidecars carry HFS+/APFS extended attributes and resource forks, are
# NOT valid UTF-8, and used to crash subject lookups on the deploy box.
# --exclude='._*' is a belt-and-braces fallback if a future macOS
# version or third-party tar respects COPYFILE_DISABLE differently.
COPYFILE_DISABLE=1 tar --exclude='._*' -czf "$TARBALL" wiki

SIZE=$(du -h "$TARBALL" | cut -f1)
echo "  archive size: $SIZE"

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "→ Release $TAG exists; replacing $ASSET asset"
  gh release upload "$TAG" "$TARBALL" --clobber
else
  echo "→ Creating release $TAG"
  gh release create "$TAG" "$TARBALL" \
    --title "Wiki corpus ($TAG)" \
    --notes "Built $(date -u +%Y-%m-%dT%H:%M:%SZ) — $MD_COUNT markdown files, $SIZE compressed."
fi

echo "✓ Published. Pull on a fresh clone with: scripts/fetch_wiki.sh $TAG"
