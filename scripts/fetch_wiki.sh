#!/usr/bin/env bash
# Pull the prebuilt wiki/ corpus from a GitHub Release and extract into ./wiki/.
#
# Required tools: gh (authenticated) OR curl (for public releases).
#
# Usage:
#   scripts/fetch_wiki.sh [TAG]
#
#   TAG    Release tag to pull from. Defaults to "wiki-latest".
#          The release must have an asset named `wiki.tar.gz`.
#
# Idempotent: if `wiki/meta/embeddings_meta.json` is already present and the
# build hash matches the release asset's, the script skips the download.
#
# Env overrides:
#   REPO         GitHub `<owner>/<repo>` slug. Defaults to the current repo
#                inferred from `git remote get-url origin`.
#   FORCE=1      Re-download even if the corpus looks current.

set -euo pipefail

TAG="${1:-wiki-latest}"
ASSET="wiki.tar.gz"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Infer REPO from git remote when not explicitly set.
if [[ -z "${REPO:-}" ]]; then
  REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
  if [[ "$REMOTE_URL" =~ github\.com[:/](.+/.+)(\.git)?$ ]]; then
    REPO="${BASH_REMATCH[1]%.git}"
  else
    echo "ERR: cannot infer REPO from git remote; set REPO=owner/repo" >&2
    exit 2
  fi
fi

echo "→ Fetching $ASSET from $REPO@$TAG ..."

if [[ -f wiki/meta/embeddings_meta.json && -z "${FORCE:-}" ]]; then
  echo "  wiki/ already present at $ROOT/wiki — skipping (FORCE=1 to override)"
  exit 0
fi

mkdir -p .cache
TARBALL=".cache/$ASSET"

if command -v gh >/dev/null 2>&1; then
  gh release download "$TAG" --repo "$REPO" -p "$ASSET" -O "$TARBALL" --clobber
else
  # Public release fallback — works without gh auth.
  URL="https://github.com/$REPO/releases/download/$TAG/$ASSET"
  echo "  gh CLI not found; falling back to curl: $URL"
  curl -fsSL -o "$TARBALL" "$URL"
fi

echo "→ Extracting into $ROOT/wiki ..."
# Wipe the destination so removed files don't linger from a previous build.
rm -rf wiki
tar -xzf "$TARBALL"
echo "✓ wiki/ corpus restored. $(find wiki -name '*.md' | wc -l | tr -d ' ') markdown files."
