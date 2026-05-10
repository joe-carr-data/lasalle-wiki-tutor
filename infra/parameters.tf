// Sensitive runtime config lives in SSM Parameter Store as SecureString
// (KMS-encrypted with the AWS-managed `aws/ssm` key). user_data fetches
// these on boot via the instance profile and writes them to /opt/app/.env.
//
// This pattern — TF holds the values, SSM is the canonical store — keeps
// the secrets out of the EC2 user_data field (which is plaintext-readable
// in the AWS console). Once they land in SSM the only on-disk copy is the
// .env file inside /opt/app on the box, scoped to the `app` user.
//
// Rotation flow (no `terraform apply` needed):
//   1. `aws ssm put-parameter --overwrite --type SecureString \
//          --name /lasalle-wiki-tutor/access-token --value <new>`
//   2. SSM-into the box, `sudo systemctl restart wiki-tutor`
//   3. The box re-reads SSM during the unit's PreStart hook.
//
// NOTE: Terraform state contains the secret values. Use a remote backend
// with encryption (S3 + KMS) before you share the workspace with anyone
// other than yourself. For a single-operator demo, local state is OK if
// `infra/.terraform/` and `terraform.tfstate*` stay out of git (they are).

resource "aws_ssm_parameter" "openai_api_key" {
  name        = local.param_openai
  description = "OpenAI API key consumed by the agent at runtime."
  type        = "SecureString"
  value       = var.openai_api_key
  tier        = "Standard"
}

resource "aws_ssm_parameter" "access_token" {
  name        = local.param_access_token
  description = "Shared secret for the gate UI; rotate to invalidate all evaluator sessions."
  type        = "SecureString"
  value       = var.wiki_tutor_access_token
  tier        = "Standard"
}
