// EC2 instance profile and the role it assumes.
//
// Two responsibilities:
//   1. SSM Session Manager — `AmazonSSMManagedInstanceCore` is the AWS-managed
//      policy that lets the SSM Agent on the box poll for commands. This is
//      how `aws ssm start-session --target <id>` opens a shell without SSH.
//   2. Read the two SecureString secrets we put in Parameter Store. Scoped to
//      the exact two parameter ARNs — least privilege.

resource "aws_iam_role" "ec2" {
  name_prefix = "${local.name_prefix}-ec2-"
  description = "Lets the demo box use SSM Session Manager and read its own secrets."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

// Grant the box read access to its own SSM parameters and the KMS key SSM
// uses to decrypt SecureStrings (the AWS-managed `aws/ssm` key, no resource
// policy hoops needed for that one).
resource "aws_iam_role_policy" "read_secrets" {
  name = "read-app-secrets"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
        ]
        Resource = [
          aws_ssm_parameter.openai_api_key.arn,
          aws_ssm_parameter.access_token.arn,
          aws_ssm_parameter.admin_token.arn,
        ]
      },
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "${local.name_prefix}-ec2-"
  role        = aws_iam_role.ec2.name
}
