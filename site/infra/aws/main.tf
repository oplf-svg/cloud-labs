# The files. Private: only this distribution can read them.
resource "aws_s3_bucket" "site" {
  bucket_prefix = "cloud-labs-site-"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.bucket

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.bucket

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# What was served stays there for 30 days after it was replaced.
resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.bucket

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket = aws_s3_bucket.site.bucket

  rule {
    id     = "old-versions"
    status = "Enabled"

    filter {}

    expiration {
      expired_object_delete_marker = true
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.site]
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.bucket

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OnlyThisDistributionReads"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = { StringEquals = { "aws:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        # So that a missing file is a 404, which CloudFront keeps, and not a 403, which it asks for again each time.
        # A visitor cannot reach the list: edge.js lets no request through to the bucket itself.
        Sid       = "MissingMeansMissing"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.site.arn
        Condition = { StringEquals = { "aws:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "TlsOnly"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.site.arn, "${aws_s3_bucket.site.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "cloud-labs-site"
  description                       = "Signs what CloudFront asks the bucket."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  # With its brackets, because Terraform takes text between two slashes for a pattern.
  edge = replace(file("${path.module}/edge.js"), "[/* addresses */]", "[${join(", ", [for address in sort(var.addresses) : jsonencode(address)])}]")
}

resource "aws_cloudfront_function" "edge" {
  name    = "cloud-labs-site"
  comment = "Keeps addresses that do not exist away from the storage."
  runtime = "cloudfront-js-2.0"
  code    = local.edge
  publish = true

  lifecycle {
    precondition {
      condition     = length(local.edge) <= 10240
      error_message = "CloudFront takes 10 KB of code for a function."
    }
  }
}

# Switched off until it is on the free plan, because without the plan a flood of requests would cost money.
resource "aws_cloudfront_distribution" "site" {
  enabled         = var.on_free_plan
  comment         = "cloud-labs site"
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    origin_id                = "bucket"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  # The free plan allows only the policies that AWS provides.
  default_cache_behavior {
    target_origin_id           = "bucket"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized: no query string, cookie or header makes a new copy
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # SecurityHeadersPolicy

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.edge.arn
    }
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 86400
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  lifecycle {
    # The plan brings its own firewall, and AWS attaches it.
    ignore_changes = [web_acl_id]
  }
}
