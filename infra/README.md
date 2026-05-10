# `infra/` — Terraform for the LaSalle Wiki Tutor demo

Provisions a single t3.micro on EC2 (eu-west-1) that runs:

- **uvicorn** (FastAPI + the React bundle) under systemd, on `127.0.0.1:8000`
- **MongoDB** in a Docker container (`docker compose up -d mongo`)
- **Caddy** in front, terminating TLS via Let's Encrypt for the domain you specify

Operations happen over **SSM Session Manager** — no port 22, no key pair. Secrets live in **SSM Parameter Store**, never in user_data or on disk in plaintext outside `/opt/app/.env` (root-readable, app-writable).

---

## Cost expectation

| Item | $/month |
|---|---|
| t3.micro (24/7 on-demand, post-free-tier) | ~$7.50 |
| 30 GB gp3 EBS root | ~$2.40 |
| EBS daily snapshots (7-day retention) | <$0.50 |
| Elastic IP (attached) | $0 |
| SSM Parameter Store (Standard tier) | $0 |
| Data egress (well under 100 GB/mo always-free) | $0 |
| **Total** | **~$10/mo** |

Stop the instance when not demoing to drop compute to $0 (EBS still bills).

---

## One-time prerequisites

1. AWS CLI logged in to the right account:

   ```bash
   aws sso login --profile traddea
   export AWS_PROFILE=traddea AWS_REGION=eu-west-1
   aws sts get-caller-identity   # confirm account 983046790277
   ```

2. Terraform 1.6+:

   ```bash
   terraform -version
   ```

3. The `wiki-latest` GitHub Release exists on `joe-carr-data/lasalle-wiki-tutor` with a `wiki.tar.gz` asset. (`scripts/publish_wiki.sh` from any machine that has `wiki/` built handles this.)

---

## Apply

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # fill domain_name, letsencrypt_email,
                           # openai_api_key, wiki_tutor_access_token

terraform init
terraform plan -out=tf.plan
terraform apply tf.plan
```

`apply` takes ~90 seconds (instance launch + EIP + IAM). The cloud-init bootstrap on the box takes another ~3-5 minutes. Watch it:

```bash
aws ssm start-session --target $(terraform output -raw instance_id)
sudo tail -f /var/log/cloud-init-output.log
# look for:  "wiki-tutor is up — bootstrap complete."
```

## Post-apply: DNS

Set the A record at GoDaddy:

```
Type:   A
Host:   lasalle    (or whatever subdomain matches var.domain_name)
Value:  <terraform output public_ip>
TTL:    600
```

Verify propagation:

```bash
dig +short lasalle.generateeve.com
```

Once DNS resolves to the EIP, hit `https://lasalle.generateeve.com/`. Caddy will hold the first request for ~10-30 seconds while it acquires the Let's Encrypt cert via HTTP-01, then return the Gate screen.

---

## Day 2

### Update the app code

```bash
aws ssm send-command \
  --document-name AWS-RunShellScript \
  --targets Key=InstanceIds,Values=$(terraform output -raw instance_id) \
  --parameters 'commands=[
    "cd /opt/app && sudo -u app git pull",
    "cd /opt/app && sudo -u app /usr/local/bin/uv sync --frozen",
    "systemctl restart wiki-tutor"
  ]'
```

### Update the wiki corpus

```bash
aws ssm send-command \
  --document-name AWS-RunShellScript \
  --targets Key=InstanceIds,Values=$(terraform output -raw instance_id) \
  --parameters 'commands=[
    "cd /opt/app && sudo -u app FORCE=1 scripts/fetch_wiki.sh wiki-latest",
    "systemctl restart wiki-tutor"
  ]'
```

### Rotate the access token

```bash
NEW=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
aws ssm put-parameter --overwrite --type SecureString \
  --name /lasalle-wiki-tutor/access-token --value "$NEW"
aws ssm send-command --document-name AWS-RunShellScript \
  --targets Key=InstanceIds,Values=$(terraform output -raw instance_id) \
  --parameters 'commands=["/usr/local/bin/refresh-app-env","systemctl restart wiki-tutor"]'
echo "New token: $NEW"
# Distribute $NEW to evaluators. Old links return 401 immediately.
```

### Stop / start to save money during long quiet periods

```bash
aws ec2 stop-instances  --instance-ids $(terraform output -raw instance_id)
aws ec2 start-instances --instance-ids $(terraform output -raw instance_id)
# EIP and EBS are preserved across stop/start.
```

### View logs

```bash
# Application:
aws ssm start-session --target $(terraform output -raw instance_id)
sudo journalctl -u wiki-tutor -f

# Caddy access log (JSON):
sudo tail -f /var/log/caddy/access.log

# Mongo:
sudo docker logs --tail 100 -f lasalle-catalog-mongo-1
```

### Tear down

```bash
terraform destroy
# Releases EIP, terminates the box, drops the EBS volume + snapshots.
# SSM parameters are deleted; rotate the OPENAI key in your account if
# you're worried about residual values in TF state on disk.
```

---

## What lives where

| Path on the box | Owned by | Purpose |
|---|---|---|
| `/opt/app/` | `app:app` | Cloned repo; `git pull` updates here. |
| `/opt/app/.venv/` | `app:app` | uv-managed Python venv. |
| `/opt/app/wiki/` | `app:app` | 50 MB corpus from the GitHub Release. |
| `/opt/app/.env` | `app:app`, mode 0600 | Rendered by `/usr/local/bin/refresh-app-env` from SSM. |
| `/etc/caddy/Caddyfile` | `root:root` | TLS + reverse proxy config. |
| `/etc/systemd/system/wiki-tutor.service` | `root:root` | Manages the uvicorn process. |
| `/swapfile` | `root:root` | 2 GB swap, prevents OOM under chat load. |
| Docker volume `mongo-data` | docker daemon | Mongo persistent storage. |

---

## Troubleshooting

- **First-boot bootstrap timed out** → SSM in, run `sudo bash /var/lib/cloud/instance/scripts/runcmd` again, or re-run the installer steps inline.
- **`terraform apply` fails on `aws_ssm_parameter`** → another stack is using the same name. Check `aws ssm describe-parameters --filters Key=Name,Values=/lasalle-wiki-tutor/`.
- **Caddy can't get cert** → DNS not yet pointing at the EIP. `dig +short <domain>` should return the EIP. Caddy retries automatically.
- **`/health` works but the chat 401s** → the user's localStorage token doesn't match the current value in SSM. Sign out (sidebar) and re-enter.
- **OOM kills during conversation** → confirm swap is on (`free -h`); if it is and we're still seeing kills, bump `instance_type = "t3.small"` in `terraform.tfvars` and re-apply (causes instance replacement; ~5 min downtime).
