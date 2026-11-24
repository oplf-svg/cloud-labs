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

output "role_arns" {
  description = "Role per repo and tier, to store later as GitHub Actions secrets. They contain the account id."
  value       = { for key, role in aws_iam_role.ci : key => role.arn }
}

output "workload_boundary_arn" {
  description = "Permissions boundary that projects must set on every role they create."
  value       = aws_iam_policy.workload_boundary.arn
}

output "trusted_subjects" {
  description = "Every subject this account trusts."
  value       = sort([for id in local.identities : id.subject])
}
