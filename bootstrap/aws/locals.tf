locals {
  issuer   = "token.actions.githubusercontent.com"
  audience = "sts.amazonaws.com"

  # The exact OIDC subjects, one per repo and tier. All three clouds read this file.
  subjects = jsondecode(file("${path.module}/../subjects.json"))

  # What each tier's subject must end with. Anything else stops the plan.
  subject_suffix = {
    plan    = "pull_request"
    apply   = "environment:production"
    destroy = "environment:nightly-destroy"
  }

  identities = merge([
    for repo, tiers in local.subjects : {
      for tier, subject in tiers : "${repo}/${tier}" => {
        repo    = repo
        tier    = tier
        subject = subject
      }
    }
  ]...)

  iam               = "arn:aws:iam::${var.account_id}"
  oidc_provider_arn = "${local.iam}:oidc-provider/${local.issuer}"

  # Paths keep the bootstrap's own IAM objects apart from what the projects create.
  ci_path              = "/github-actions/"
  ci_roles             = "${local.iam}:role${local.ci_path}*"
  ci_policies          = "${local.iam}:policy${local.ci_path}*"
  service_roles        = "${local.iam}:role/aws-service-role/*"
  workload_path        = "/workload/"
  workload_roles       = "${local.iam}:role${local.workload_path}*"
  workload_policies    = "${local.iam}:policy${local.workload_path}*"
  workload_profiles    = "${local.iam}:instance-profile${local.workload_path}*"
  workload_boundary    = "${local.iam}:policy${local.ci_path}workload-boundary"
  eks_instance_profile = "${local.iam}:instance-profile/eks*"

  role_arns = {
    for key, id in local.identities : key => "${local.iam}:role${local.ci_path}gha-${id.repo}-${id.tier}"
  }

  bucket_arn = "arn:aws:s3:::tfstate-${random_id.suffix.hex}"
}
