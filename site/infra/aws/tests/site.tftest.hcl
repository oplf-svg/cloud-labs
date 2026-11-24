# Against a stand-in for AWS. Nothing real is called.
mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      arn    = "arn:aws:s3:::cloud-labs-site-example"
      bucket = "cloud-labs-site-example"
    }
  }

  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::111122223333:function/cloud-labs-site" }
  }

  mock_resource "aws_cloudfront_distribution" {
    defaults = { arn = "arn:aws:cloudfront::111122223333:distribution/EXAMPLE" }
  }
}

variables {
  account_id   = "111122223333"
  addresses    = ["/", "/proof/", "/favicon.svg"]
  on_free_plan = false
}

run "off_until_it_is_on_the_free_plan" {
  command = plan

  assert {
    condition     = aws_cloudfront_distribution.site.enabled == false
    error_message = "A distribution that is not on the free plan must not be reachable."
  }
}

run "on_once_it_is" {
  command = plan

  variables {
    on_free_plan = true
  }

  assert {
    condition     = aws_cloudfront_distribution.site.enabled
    error_message = "On the free plan it has to be reachable."
  }
}

run "only_this_distribution_reads_the_files" {
  assert {
    condition = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s if s.Effect == "Allow"] == [
      {
        Sid       = "OnlyThisDistributionReads"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = { StringEquals = { "aws:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "MissingMeansMissing"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.site.arn
        Condition = { StringEquals = { "aws:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
    ]
    error_message = "The bucket lets in something other than this distribution."
  }

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.site.block_public_acls,
      aws_s3_bucket_public_access_block.site.block_public_policy,
      aws_s3_bucket_public_access_block.site.ignore_public_acls,
      aws_s3_bucket_public_access_block.site.restrict_public_buckets,
    ])
    error_message = "The bucket could be made public."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.origin).origin_access_control_id == aws_cloudfront_origin_access_control.site.id
    error_message = "CloudFront does not sign what it asks the bucket."
  }
}

run "takes_nothing_from_visitors" {
  command = plan

  assert {
    condition     = toset(one(aws_cloudfront_distribution.site.default_cache_behavior).allowed_methods) == toset(["GET", "HEAD"])
    error_message = "Visitors may only read."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.default_cache_behavior).viewer_protocol_policy == "redirect-to-https"
    error_message = "Nothing may be served without TLS."
  }
}

run "needs_only_what_the_free_plan_allows" {
  command = plan

  assert {
    condition = alltrue([
      one(aws_cloudfront_distribution.site.default_cache_behavior).cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6",
      one(aws_cloudfront_distribution.site.default_cache_behavior).response_headers_policy_id == "67f7725c-6f97-4210-82d7-5512b31e9d03",
      length(coalesce(aws_cloudfront_distribution.site.ordered_cache_behavior, [])) == 0,
      length(coalesce(aws_cloudfront_distribution.site.logging_config, [])) == 0,
      length(aws_cloudfront_distribution.site.origin) == 1,
    ])
    error_message = "The free plan has no policies of one's own, no real-time logs and no second origin."
  }
}

run "keeps_unknown_addresses_away_from_the_storage" {
  command = plan

  assert {
    condition     = strcontains(aws_cloudfront_function.edge.code, "const addresses = [\"/\", \"/favicon.svg\", \"/proof/\"];")
    error_message = "The function does not know the addresses of the site."
  }

  assert {
    condition     = one(one(aws_cloudfront_distribution.site.default_cache_behavior).function_association).event_type == "viewer-request" && aws_cloudfront_function.edge.publish
    error_message = "The function has to come before the cache."
  }

  # CloudFront keeps only some errors, and 403 is not one of them.
  assert {
    condition = one(aws_cloudfront_distribution.site.custom_error_response) == {
      error_code            = 404
      response_code         = 404
      response_page_path    = "/404.html"
      error_caching_min_ttl = 86400
    }
    error_message = "An address that does not exist has to say so, and the storage must not be asked about it again."
  }

  # With a root object, / could reach the function as /index.html, which it sends back to /.
  assert {
    condition     = aws_cloudfront_distribution.site.default_root_object == null
    error_message = "The function looks after the start page."
  }
}

run "refuses_a_list_without_the_start_page" {
  command         = plan
  expect_failures = [var.addresses]

  variables {
    addresses = ["/proof/"]
  }
}

run "refuses_code_among_the_addresses" {
  command         = plan
  expect_failures = [var.addresses]

  variables {
    addresses = ["/", "/\"]; stolen(); //"]
  }
}

run "refuses_a_way_up" {
  command         = plan
  expect_failures = [var.addresses]

  variables {
    addresses = ["/", "/../other/"]
  }
}

run "refuses_a_function_that_is_too_big" {
  command         = plan
  expect_failures = [aws_cloudfront_function.edge]

  variables {
    addresses = concat(["/"], [for i in range(400) : "/a-page-with-a-rather-long-name-${i}/"])
  }
}

run "refuses_another_kind_of_account" {
  command         = plan
  expect_failures = [var.account_id]

  variables {
    account_id = "my account"
  }
}
