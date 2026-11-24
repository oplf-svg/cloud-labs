resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  bucket        = "tfstate-${random_id.suffix.hex}"
  force_destroy = var.allow_state_deletion

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.bucket

  versioning_configuration {
    status = "Enabled"
  }
}

# Keys managed by S3. A customer key would add a fixed monthly cost on each cloud.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.bucket

  rule {
    blocked_encryption_types = ["SSE-C"]

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.bucket

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.bucket

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.bucket

  rule {
    id     = "old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 10
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

locals {
  repo_role_arns = {
    for repo in keys(local.subjects) : repo => [for tier in keys(local.subject_suffix) : local.role_arns["${repo}/${tier}"]]
  }

  # Per role: read its own repo's state. Apply and destroy also write it and hold the lock.
  state_policies = {
    for key, id in local.identities : key => {
      Version = "2012-10-17"
      Statement = concat(
        [
          {
            Sid      = "FindState"
            Effect   = "Allow"
            Action   = ["s3:ListBucket"]
            Resource = local.bucket_arn
          },
          {
            Sid      = "ReadOwnState"
            Effect   = "Allow"
            Action   = ["s3:GetObject"]
            Resource = "${local.bucket_arn}/${id.repo}/*"
          },
        ],
        id.tier == "plan" ? [] : [
          {
            Sid      = "WriteOwnState"
            Effect   = "Allow"
            Action   = ["s3:PutObject"]
            Resource = "${local.bucket_arn}/${id.repo}/*"
          },
          {
            Sid      = "ReleaseOwnLock"
            Effect   = "Allow"
            Action   = ["s3:DeleteObject"]
            Resource = "${local.bucket_arn}/${id.repo}/*.tflock"
          },
        ],
      )
    }
  }
}

# The bucket also defends itself, because PowerUserAccess allows s3:* on everything.
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.bucket

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid       = "TlsOnly"
          Effect    = "Deny"
          Principal = "*"
          Action    = "s3:*"
          Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
          Condition = { Bool = { "aws:SecureTransport" = "false" } }
        },
        {
          Sid       = "Tls12OrNewer"
          Effect    = "Deny"
          Principal = "*"
          Action    = "s3:*"
          Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
          Condition = { NumericLessThan = { "s3:TlsVersion" = "1.2" } }
        },
        {
          Sid       = "PipelinesCannotChangeTheBucket"
          Effect    = "Deny"
          Principal = "*"
          NotAction = ["s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:ListBucket"]
          Resource  = local.bucket_arn
          Condition = { ArnLike = { "aws:PrincipalArn" = local.ci_roles } }
        },
        {
          Sid       = "PipelinesCannotEraseHistory"
          Effect    = "Deny"
          Principal = "*"
          Action    = ["s3:BypassGovernanceRetention", "s3:DeleteObjectVersion", "s3:PutObjectAcl", "s3:PutObjectVersionAcl"]
          Resource  = "${local.bucket_arn}/*"
          Condition = { ArnLike = { "aws:PrincipalArn" = local.ci_roles } }
        },
        {
          # Some AWS services read buckets with roles of their own, on behalf of whoever turned them on.
          Sid       = "ServicesCannotReadState"
          Effect    = "Deny"
          Principal = "*"
          Action    = "s3:*"
          Resource  = "${local.bucket_arn}/*"
          Condition = { ArnLike = { "aws:PrincipalArn" = local.service_roles } }
        },
        {
          Sid       = "WorkloadsCannotTouchState"
          Effect    = "Deny"
          Principal = "*"
          Action    = "s3:*"
          Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
          Condition = { ArnLike = { "aws:PrincipalArn" = local.workload_roles } }
        },
      ],
      [
        for repo, arns in local.repo_role_arns : {
          Sid         = "OnlyOwnState${replace(title(replace(repo, "-", " ")), " ", "")}"
          Effect      = "Deny"
          Principal   = "*"
          Action      = "s3:*"
          NotResource = [local.bucket_arn, "${local.bucket_arn}/${repo}/*"]
          Condition   = { ArnEquals = { "aws:PrincipalArn" = arns } }
        }
      ],
    )
  })

  depends_on = [aws_s3_bucket_public_access_block.state]
}
