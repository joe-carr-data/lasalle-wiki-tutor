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

## AWS demo: t3.micro + Caddy (Terraform-managed)

Goal: public URL `https://lasalle.generateeve.com`, HTTPS via Let's Encrypt,
gated by `WIKI_TUTOR_ACCESS_TOKEN`. Single t3.micro in `eu-west-1`, no SSH
(SSM Session Manager only), Mongo in compose alongside the app, frontend
served from FastAPI's bundled `dist/`. Cost ~$10/mo on-demand.

The provisioning is in [`infra/`](../infra/) — Terraform module that lays
down the VPC bits, the SSM-managed instance profile, the EBS-snapshot
lifecycle, and a `cloud-init` bootstrap that installs Docker, Caddy,
fetches the wiki release, renders `.env` from SSM Parameter Store, and
starts everything as systemd services.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars      # domain_name, letsencrypt_email,
                              # openai_api_key, wiki_tutor_access_token
terraform init
terraform apply
```

Apply takes ~90s for the AWS resources; the box's first boot bootstrap is
another 3-5 min. Watch progress over SSM:

```bash
aws ssm start-session --target $(terraform output -raw instance_id)
sudo tail -f /var/log/cloud-init-output.log
```

Then set the A record at GoDaddy: `lasalle.generateeve.com` → the EIP from
`terraform output public_ip`. Hit the URL once DNS resolves; Caddy holds
the first request ~10-30s while it acquires the cert.

Full runbook (rotation, updates, troubleshooting): [`infra/README.md`](../infra/README.md).

### Manual fallback (if you can't run Terraform)

Same shape, by hand:

```bash
# AWS console:
#   - launch t3.micro Ubuntu 24.04 in eu-west-1, default VPC.
#   - attach an IAM instance profile with AmazonSSMManagedInstanceCore.
#   - security group: 80, 443 inbound; egress all. NO port 22.
#   - allocate + attach an Elastic IP.

aws ssm start-session --target i-xxxxxxxx     # no SSH key needed
sudo apt update && sudo apt install -y docker.io docker-compose-plugin caddy git
sudo usermod -aG docker ubuntu && newgrp docker

git clone https://github.com/joe-carr-data/lasalle-wiki-tutor.git /opt/app
cd /opt/app
cp .env.example .env
# edit .env: real OPENAI_API_KEY + a fresh WIKI_TUTOR_ACCESS_TOKEN
scripts/fetch_wiki.sh

# Mongo only — uvicorn runs natively under systemd.
docker compose up -d mongo

uv sync
# Render Caddyfile + systemd unit (see infra/templates/user_data.sh.tftpl
# for the canonical content).
sudo systemctl reload caddy
sudo systemctl enable --now wiki-tutor.service
```

### Caddy in front (auto-HTTPS)

`/etc/caddy/Caddyfile`:

```caddy
{
    email <your-email>
}

lasalle.generateeve.com {
    encode zstd gzip

    # SSE needs no buffering; keep connections open for long agent runs.
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
        transport http {
            keepalive 5m
            response_header_timeout 5m
        }
    }

    log {
        output file /var/log/caddy/access.log {
            roll_size 50mb
            roll_keep 5
        }
        format json
    }
}
```

Reload: `sudo systemctl reload caddy`. Caddy obtains a Let's Encrypt cert
on first request and auto-renews.

### Operations (manual path)

```bash
# Push code:                  git push   (on dev box)
# Pull on the EC2:            cd /opt/app && git pull && uv sync && sudo systemctl restart wiki-tutor
# Update wiki corpus:         FORCE=1 scripts/fetch_wiki.sh && sudo systemctl restart wiki-tutor
# Rotate the access token:
#   1. edit /opt/app/.env:    WIKI_TUTOR_ACCESS_TOKEN=<new>
#   2. sudo systemctl restart wiki-tutor
#   3. distribute the new token; old links 401 immediately.
```

The Terraform path automates rotation through SSM Parameter Store — see
`infra/README.md`.

### Rate-limiting the gate

Application-level rate limiting is already in `core/auth.py` (10 attempts
per IP per minute on `/api/auth/validate`). Caddy-level is defense in
depth; install the rate-limit plugin if you want it:

```caddy
lasalle.generateeve.com {
    @gate path /api/auth/validate
    rate_limit @gate {
        zone gate {
            key {http.request.remote_host}
            events 10
            window 1m
        }
    }
    reverse_proxy 127.0.0.1:8000 { ... }
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
