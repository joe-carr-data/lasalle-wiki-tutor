// Inputs for the LaSalle Wiki Tutor demo deploy. The defaults match the
// agreed plan: single t3.micro in eu-west-1, accessed only via SSM, with the
// frontend-served-from-FastAPI architecture and Mongo running in compose
// alongside the app on the same box.

variable "project" {
  description = "Tag value applied to every resource for cost reporting and cleanup."
  type        = string
  default     = "lasalle-wiki-tutor"
}

variable "aws_region" {
  description = "AWS region. eu-west-1 is the agreed default — closest to LaSalle Barcelona evaluators."
  type        = string
  default     = "eu-west-1"
}

variable "instance_type" {
  description = "EC2 instance type. t3.micro is sufficient with a 2 GB swap file."
  type        = string
  default     = "t3.micro"
}

variable "root_volume_gb" {
  description = "Root EBS volume size in GB. 30 = comfortable for OS + Docker images + wiki/ + Mongo data + room to debug."
  type        = number
  default     = 30
}

variable "domain_name" {
  description = "Public hostname Caddy will obtain a Let's Encrypt cert for. You set the A record at your DNS provider after `terraform apply`, pointing at `eip` from outputs."
  type        = string
  // No default — user must specify so the cert request matches reality.
}

variable "letsencrypt_email" {
  description = "Email Caddy registers with Let's Encrypt (used for cert expiry warnings)."
  type        = string
}

variable "git_repo_url" {
  description = "Public HTTPS clone URL for the application repo. user_data clones this into /opt/app."
  type        = string
  default     = "https://github.com/joe-carr-data/lasalle-wiki-tutor.git"
}

variable "git_branch" {
  description = "Branch the EC2 box tracks. Updates flow via `git pull` during ./deploy.sh."
  type        = string
  default     = "main"
}

variable "wiki_release_tag" {
  description = "Tag of the wiki corpus GitHub Release that user_data fetches. `wiki-latest` is a rolling tag updated by scripts/publish_wiki.sh."
  type        = string
  default     = "wiki-latest"
}

variable "openai_api_key" {
  description = "OpenAI API key. Stored in SSM Parameter Store (encrypted) and read by the EC2 box at boot via its instance profile."
  type        = string
  sensitive   = true
}

variable "wiki_tutor_access_token" {
  description = "Shared secret for the gate UI. Distribute out-of-band to evaluators. Generate with `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`."
  type        = string
  sensitive   = true
}

variable "wiki_tutor_admin_token" {
  description = "Secondary secret gating /api/admin/* (the IP roster dashboard). Required as the X-Admin-Token header in addition to the loopback source check. Generate with the same `secrets.token_urlsafe(32)` recipe. Distribute only to operators, never to evaluators."
  type        = string
  sensitive   = true
}
