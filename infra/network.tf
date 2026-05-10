// Security group for the demo box.
//
// Ingress: 80 + 443 from anywhere (Caddy needs both — 80 for the HTTP-01
// ACME challenge and the HTTP→HTTPS redirect, 443 for the actual app).
//
// Egress: unrestricted (apt updates, OpenAI API, GitHub clone, package
// repos, Let's Encrypt). Tightening egress is overkill for a demo.
//
// Notably absent: port 22. Operations happen via SSM Session Manager, which
// uses an outbound HTTPS poll from the SSM Agent — no inbound port. See
// iam.tf for the role that grants the box SSM access.

resource "aws_security_group" "wiki_tutor" {
  name_prefix = "${local.name_prefix}-"
  // SG descriptions must be ASCII-only and match [a-zA-Z0-9. _-:/()#,@[\]+=&;{}!$*]+
  description = "LaSalle Wiki Tutor public web only, no SSH (SSM-managed)."
  vpc_id      = data.aws_vpc.default.id

  // Allow re-creating the SG without breaking the EC2 dependency: when the
  // SG changes, Terraform creates the new one before destroying the old.
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.wiki_tutor.id
  description       = "HTTP for ACME HTTP-01 and redirect to HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.wiki_tutor.id
  description       = "HTTPS public app traffic"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.wiki_tutor.id
  description       = "All outbound for apt OpenAI GitHub and Lets Encrypt"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
