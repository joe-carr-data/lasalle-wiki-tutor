// Provider, data sources, and tag locals shared by the rest of the stack.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "wiki-tutor-demo"
    }
  }
}

// Default VPC — fine for a single demo box. We don't need private subnets,
// NAT gateways, or VPC endpoints for this scale.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

// Latest Canonical Ubuntu 24.04 LTS, x86_64, gp3-backed.
// Owner 099720109477 = Canonical, the official publisher.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  // Names baked into more than one resource — keeping them as locals avoids
  // copy-paste drift when we rename the project later.
  name_prefix        = var.project
  param_openai       = "/${var.project}/openai-api-key"
  param_access_token = "/${var.project}/access-token"
  app_dir            = "/opt/app"
}
