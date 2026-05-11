// EC2 instance + Elastic IP + EBS root volume.
//
// Single t3.micro in the default VPC, public subnet (the default subnets
// in `data.aws_subnets.default` ARE public — they auto-assign a public IP
// and have an internet gateway route). We attach a dedicated Elastic IP
// so the public address is stable across stop/start cycles.

// Render the cloud-init script with the values it needs at first-boot.
// Anything dynamic — the hostname Caddy serves, parameter ARNs, repo URL,
// release tag — gets templated in here so we don't keep secrets or runtime
// names duplicated across files.
data "cloudinit_config" "user_data" {
  gzip          = true
  base64_encode = true

  part {
    content_type = "text/x-shellscript"
    filename     = "bootstrap.sh"
    content = templatefile("${path.module}/templates/user_data.sh.tftpl", {
      domain_name        = var.domain_name
      letsencrypt_email  = var.letsencrypt_email
      git_repo_url       = var.git_repo_url
      git_branch         = var.git_branch
      wiki_release_tag   = var.wiki_release_tag
      app_dir            = local.app_dir
      param_openai       = aws_ssm_parameter.openai_api_key.name
      param_access_token = aws_ssm_parameter.access_token.name
      param_admin_token  = aws_ssm_parameter.admin_token.name
      aws_region         = var.aws_region
    })
  }
}

resource "aws_instance" "wiki_tutor" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.wiki_tutor.id]
  // Pick the first default subnet — any AZ in the region is fine for a
  // single-box demo, and `aws_subnets.default` already filters to default
  // subnets that have IGW routes.
  subnet_id = data.aws_subnets.default.ids[0]

  iam_instance_profile = aws_iam_instance_profile.ec2.name

  // Force IMDSv2 — the SSM Agent and any AWS SDK call from inside the box
  // negotiates v2 transparently, but legacy v1 metadata access is a known
  // SSRF amplifier. AWS recommends required, not optional.
  //
  // hop_limit = 1 means containers (which sit one hop away across docker0)
  // cannot reach IMDS — that's the security posture we want. The native
  // uvicorn process and the host-level SSM agent are still 0 hops away
  // from the metadata service, so they keep working.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    delete_on_termination = true
    encrypted             = true
    tags = {
      Name = "${local.name_prefix}-root"
    }
  }

  user_data                   = data.cloudinit_config.user_data.rendered
  user_data_replace_on_change = false

  // Cleanup-friendly: a stop without `disable_api_termination` keeps the
  // box destroyable via plain `terraform destroy`. Fine for a demo.
  disable_api_termination = false

  tags = {
    Name = "${local.name_prefix}-app"
  }

  lifecycle {
    // Don't replace the box every time we tweak the cloud-init template —
    // we re-run the bootstrap manually over SSM if we want to apply changes.
    ignore_changes = [
      ami, // Canonical re-tags the AMI periodically; we don't want a new instance every plan.
      user_data,
    ]
  }
}

// Stable public IP. EIPs attached to a running instance are free; an EIP
// allocated but NOT attached costs ~$3.60/mo, so don't release the box
// without releasing the EIP.
resource "aws_eip" "wiki_tutor" {
  domain   = "vpc"
  instance = aws_instance.wiki_tutor.id

  tags = {
    Name = "${local.name_prefix}-eip"
  }
}
