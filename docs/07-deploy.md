# Phase 6 — Deployment

Last updated: 2026-05-10

This doc covers the two scenarios you actually need to bootstrap the project
end-to-end:

1. **Fresh clone on a developer machine** — get the chat running locally in
   a few minutes without re-crawling salleurl.edu.
2. **Public demo on AWS** — single t3.micro EC2 with HTTPS, behind the
   `WIKI_TUTOR_ACCESS_TOKEN` gate.

The shared piece is the **wiki corpus**: 50 MB of generated markdown +
retrieval sidecars (`wiki/`) that the agent reads from. It's gitignored on
purpose — too big for routine git, easily rebuildable from the 880 MB
`data/` crawl. We ship it as a GitHub Release asset and pull it on demand.

## Bootstrap a fresh clone

```bash
git clone https://github.com/joe-carr-data/lasalle-wiki-tutor.git
cd lasalle-wiki-tutor

# 1. Secrets
cp .env.example .env
# Fill OPENAI_API_KEY and (for non-localhost) WIKI_TUTOR_ACCESS_TOKEN.
# Generate a fresh token with:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Python deps
uv sync

# 3. The wiki corpus (50 MB, fetched from a GitHub Release)
scripts/fetch_wiki.sh         # pulls the rolling `wiki-latest` tag
# or pin a specific snapshot:
# scripts/fetch_wiki.sh wiki-2026-05-10

# 4. MongoDB
docker compose up -d mongo    # or any local mongo on :27017

# 5. Run
set -a; source .env; set +a
uv run uvicorn streaming:app --port 8000
# open http://localhost:8000 — Gate screen prompts for the access token.
```

`scripts/fetch_wiki.sh` is idempotent — re-running it on a populated `wiki/`
is a no-op unless you pass `FORCE=1`.

## Publishing a new wiki snapshot

When you rebuild the corpus (re-crawl + `scripts/build_wiki.py` +
`scripts/build_embeddings.py`), upload it so other clones can pull it:

```bash
scripts/publish_wiki.sh                  # updates the rolling wiki-latest tag
scripts/publish_wiki.sh wiki-2026-05-10  # also pin a versioned snapshot
```

The script refuses to publish if `wiki/` looks partial (fewer than 100
markdown files, or missing the embeddings metadata).

## AWS demo: t3.micro + Caddy

Goal: public URL, HTTPS via Let's Encrypt, gated by
`WIKI_TUTOR_ACCESS_TOKEN`. Cost ≈ $8/mo on-demand, less reserved.

### One-time setup

```bash
# On AWS console / CLI:
# - launch t3.micro Ubuntu 22.04, security group allows 22, 80, 443.
# - assign an Elastic IP and a Route 53 A record (e.g. tutor.salleurl-demo.com).

ssh ubuntu@tutor.salleurl-demo.com
sudo apt update && sudo apt install -y docker.io docker-compose-plugin caddy git
sudo usermod -aG docker $USER && newgrp docker

# Clone + bootstrap (mirrors the dev workflow above):
git clone https://github.com/joe-carr-data/lasalle-wiki-tutor.git
cd lasalle-wiki-tutor
cp .env.example .env
# edit .env: real OPENAI_API_KEY + a fresh WIKI_TUTOR_ACCESS_TOKEN
scripts/fetch_wiki.sh

docker compose up -d --build      # starts mongo + the app on :8000
```

### Caddy in front (auto-HTTPS)

Create `/etc/caddy/Caddyfile`:

```caddy
tutor.salleurl-demo.com {
    encode zstd gzip

    # SSE needs no buffering; keep connections open for long agent runs.
    reverse_proxy localhost:8000 {
        flush_interval -1
        transport http {
            keepalive 5m
            response_header_timeout 5m
        }
    }

    log {
        output file /var/log/caddy/tutor.log {
            roll_size 100mb
            roll_keep 5
        }
    }
}
```

Reload: `sudo systemctl reload caddy`. Caddy obtains a Let's Encrypt cert on
first request and auto-renews.

### Operations

```bash
# Push code:                  git push   (on dev box)
# Pull on the EC2:            git pull && docker compose up -d --build
# Update wiki corpus:         scripts/fetch_wiki.sh && docker compose restart app
# Rotate the access token:
#   1. edit .env on the EC2:   WIKI_TUTOR_ACCESS_TOKEN=<new>
#   2. docker compose up -d   (restarts the app with the new env)
#   3. distribute the new token; old links 401 immediately.
```

### Rate-limiting the gate

The `POST /api/auth/validate` endpoint should be rate-limited per IP to
prevent brute-forcing a 32-char token. Caddy can do it with the
`rate_limit` plugin:

```caddy
tutor.salleurl-demo.com {
    @gate path /api/auth/validate
    rate_limit @gate {
        zone gate {
            key {http.request.remote_host}
            events 10
            window 1m
        }
    }
    reverse_proxy localhost:8000 { ... }
}
```

(Plugin install: `caddy add-package github.com/mholt/caddy-ratelimit`.)

## What lives where

| Path | In git? | Where it comes from on a fresh clone |
|---|---|---|
| `frontend/dist/` | yes | committed; rebuilt by Docker stage 1 |
| `wiki/` | no | `scripts/fetch_wiki.sh` from a Release asset |
| `data/` | no | only needed to rebuild `wiki/`; recrawl with `scripts/fetch_catalog.py` |
| `.env` | no | copied from `.env.example` and filled by hand |
| `.venv/` | no | `uv sync` |
| `frontend/node_modules/` | no | only needed for `npm run dev`; Docker builds bring their own |
| Mongo data | no | persisted in the Docker volume `mongo_data` |

## Troubleshooting

- **Agent answers are empty / 0 search results** — `wiki/` is missing. Run
  `scripts/fetch_wiki.sh`.
- **Streaming endpoint 401s** — `WIKI_TUTOR_ACCESS_TOKEN` env var doesn't
  match the token in localStorage. Sign out (sidebar button) and re-enter.
- **Caddy says cert challenge failed** — DNS isn't pointing at the EC2's
  Elastic IP yet. Verify with `dig tutor.salleurl-demo.com`.
- **Mongo auth errors locally** — the docker `mongo:6.0` runs without auth.
  Make sure `MONGO_URL=mongodb://localhost:27017` (no `admin:password@`).
