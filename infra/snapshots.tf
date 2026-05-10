// Daily EBS snapshots via Data Lifecycle Manager.
//
// The Mongo working set lives on the root volume (the docker volume
// `mongo-data` is on the same filesystem). DLM snapshots are the cheapest
// "backup" for a single-box demo: ~$0.05/GB/month for snapshot storage,
// fully managed, no cron jobs, no S3 buckets.
//
// Retention: 7 daily snapshots. Tail-rolling: each new snapshot drops the
// oldest, so total snapshot storage tops out at ~7 × delta-from-baseline,
// which for a demo with light writes is tiny.

resource "aws_iam_role" "dlm" {
  name_prefix = "${local.name_prefix}-dlm-"
  description = "Lets Data Lifecycle Manager snapshot the demo box's EBS volume."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "dlm.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "dlm_default" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "daily" {
  // DLM description must match [0-9A-Za-z _-]+ — no Unicode dashes or punctuation.
  description        = "${local.name_prefix} daily root volume snapshots 7 day retention"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    target_tags = {
      Name = "${local.name_prefix}-root"
    }

    schedule {
      name = "daily-7-day-retention"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        // 03:00 UTC ≈ 04:00 Madrid local — quietest hour for a Spain-based demo.
        times = ["03:00"]
      }

      retain_rule {
        count = 7
      }

      copy_tags = true
    }
  }
}
