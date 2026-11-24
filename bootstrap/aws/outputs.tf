output "backend_tf" {
  description = "Backend block for this stack's own state. Write it to backend.tf, which git ignores."
  value       = <<-EOT
    terraform {
      backend "s3" {
        bucket       = "${aws_s3_bucket.state.bucket}"
        key          = "bootstrap/terraform.tfstate"
        region       = "${var.region}"
        encrypt      = true
        use_lockfile = true
      }
    }
  EOT
}

output "state_bucket" {
  description = "Bucket for every repo's state. Each repo uses keys under its own name."
  value       = aws_s3_bucket.state.bucket
}

output "github_secrets" {
  description = "Input for scripts/load_secrets.py. A job in production, nightly-destroy or cost gets that environment's value, any other job gets the plan role, which only a job in plan can use."
  sensitive   = true

  value = {
    cloud = "aws"
    repos = {
      for repo in keys(local.subjects) : repo => merge({
        repository = {
          AWS_ACCOUNT_ID            = var.account_id
          AWS_ROLE_ARN              = aws_iam_role.ci["${repo}/plan"].arn
          AWS_STATE_BUCKET          = aws_s3_bucket.state.bucket
          AWS_WORKLOAD_BOUNDARY_ARN = aws_iam_policy.workload_boundary.arn
        }
        production = {
          AWS_ROLE_ARN = aws_iam_role.ci["${repo}/apply"].arn
        }
        nightly-destroy = {
          AWS_ROLE_ARN = aws_iam_role.ci["${repo}/destroy"].arn
        }
      }, { for name, secrets in local.cost_secrets : name => secrets if repo == "cloud-labs" })
    }
  }
}

output "trusted_subjects" {
  description = "Every subject this account trusts."
  value       = sort(concat([for id in local.identities : id.subject], [local.cost_subject]))
}
