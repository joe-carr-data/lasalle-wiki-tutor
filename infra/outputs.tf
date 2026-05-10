output "instance_id" {
  description = "EC2 instance ID. Use with `aws ssm start-session --target <id>`."
  value       = aws_instance.wiki_tutor.id
}

output "public_ip" {
  description = "Elastic IP. Set this as the A record at GoDaddy for `var.domain_name`."
  value       = aws_eip.wiki_tutor.public_ip
}

output "domain_name" {
  description = "Hostname Caddy will serve and request a Let's Encrypt cert for."
  value       = var.domain_name
}

output "ssm_session_command" {
  description = "Copy/paste to open an interactive shell on the box."
  value       = "AWS_PROFILE=traddea aws ssm start-session --target ${aws_instance.wiki_tutor.id} --region ${var.aws_region}"
}

output "next_steps" {
  description = "What to do after a successful apply."
  value       = <<-EOT
    1. Set DNS at GoDaddy: A record  ${var.domain_name}  →  ${aws_eip.wiki_tutor.public_ip}
       (TTL 600 is fine. Wait for `dig +short ${var.domain_name}` to return the IP.)

    2. The first boot bootstrap takes ~3-5 minutes. Watch progress with:
         aws ssm start-session --target ${aws_instance.wiki_tutor.id} --region ${var.aws_region}
         sudo tail -f /var/log/cloud-init-output.log

    3. Once the boot finishes, hit https://${var.domain_name}/ — the Gate
       should appear. The first request triggers Caddy's Let's Encrypt
       acquisition; allow ~30s for the cert handshake.

    4. To rotate the access token without redeploying:
         aws ssm put-parameter --overwrite --type SecureString \\
             --name ${aws_ssm_parameter.access_token.name} \\
             --value $(python -c "import secrets; print(secrets.token_urlsafe(32))")
         aws ssm send-command --document-name AWS-RunShellScript \\
             --targets Key=InstanceIds,Values=${aws_instance.wiki_tutor.id} \\
             --parameters 'commands=["/usr/local/bin/refresh-app-env"]'
  EOT
}
