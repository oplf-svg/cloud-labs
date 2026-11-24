# Runs against mocked providers: no credentials, nothing is created.

mock_provider "aws" {}

# Each policy has an ARN of its own, so that the tests can tell them apart.
override_resource {
  target = aws_iam_policy.guardrails
  values = { arn = "arn:aws:iam::111122223333:policy/github-actions/guardrails" }
}

override_resource {
  target = aws_iam_policy.read_extras
  values = { arn = "arn:aws:iam::111122223333:policy/github-actions/read-extras" }
}

override_resource {
  target = aws_iam_policy.workload_boundary
  values = { arn = "arn:aws:iam::111122223333:policy/github-actions/workload-boundary" }
}

override_resource {
  target = aws_iam_policy.workload_iam
  values = { arn = "arn:aws:iam::111122223333:policy/github-actions/workload-iam" }
}

override_resource {
  target = aws_iam_policy.delete
  values = { arn = "arn:aws:iam::111122223333:policy/github-actions/delete" }
}

mock_provider "random" {
  mock_resource "random_id" {
    defaults = { hex = "0a1b2c3d" }
  }
}

variables {
  account_id = "111122223333"

  # Written out again here on purpose, so that a change to subjects.json fails the test.
  repo_ids = {
    webhook-platform   = 1469384538
    k8s-platform-lab   = 1469385215
    ai-ops-agent       = 1469385344
    event-pipeline-lab = 1469385472
    cloud-labs         = 1469385611
  }
  suffixes = {
    plan    = "environment:plan:ref:refs/heads/main"
    apply   = "environment:production:ref:refs/heads/main"
    destroy = "environment:nightly-destroy:ref:refs/heads/main"
  }
  cost_subject = "repo:oplf-svg@228823995/cloud-labs@1469385611:environment:cost:ref:refs/heads/main"
}

run "trust" {
  command = apply

  assert {
    condition = { for key, role in aws_iam_role.ci : key => jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] } == merge([
      for repo, id in var.repo_ids : { for tier, suffix in var.suffixes : "${repo}/${tier}" => "repo:oplf-svg@228823995/${repo}@${id}:${suffix}" }
    ]...)
    error_message = "Every role must trust exactly one literal subject, for its own repo and tier."
  }

  assert {
    condition     = length(aws_iam_role.ci) == 15
    error_message = "Five repos with three tiers each make 15 roles."
  }

  assert {
    condition = alltrue([
      for role in aws_iam_role.ci : !strcontains(role.assume_role_policy, "*") && !strcontains(role.assume_role_policy, "StringLike")
    ])
    error_message = "Trust policies must not use wildcards."
  }

  assert {
    condition = alltrue([
      for role in aws_iam_role.ci :
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
      && length(jsondecode(role.assume_role_policy).Statement) == 1
      && jsondecode(role.assume_role_policy).Statement[0].Action == "sts:AssumeRoleWithWebIdentity"
    ])
    error_message = "Each trust policy is one web identity statement with the STS audience."
  }

  assert {
    condition = alltrue([
      for role in aws_iam_role.ci :
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:ref"] == "refs/heads/main"
    ])
    error_message = "Every role must also require the main branch."
  }

  assert {
    condition = alltrue([
      for role in aws_iam_role.ci :
      can(regex(":environment:(plan|production|nightly-destroy):ref:refs/heads/main$", jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]))
    ])
    error_message = "Only jobs in one of the three environments and on main may be trusted, so never a pull request."
  }
}

run "permissions" {
  command = apply

  assert {
    condition = { for key, a in aws_iam_role_policy_attachment.ci : a.role => a.policy_arn... if endswith(key, "/power-user") } == {
      for repo, id in var.repo_ids : "gha-${repo}-apply" => ["arn:aws:iam::aws:policy/PowerUserAccess"]
    }
    error_message = "Only the apply roles may have PowerUserAccess."
  }

  assert {
    condition = { for role in distinct([for a in aws_iam_role_policy_attachment.ci : a.role]) : role => toset([for a in aws_iam_role_policy_attachment.ci : a.policy_arn if a.role == role]) } == merge([
      for repo, id in var.repo_ids : {
        "gha-${repo}-plan" = toset([
          "arn:aws:iam::aws:policy/SecurityAudit",
          "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess",
          "arn:aws:iam::111122223333:policy/github-actions/read-extras",
          "arn:aws:iam::111122223333:policy/github-actions/guardrails",
        ])
        "gha-${repo}-apply" = toset([
          "arn:aws:iam::aws:policy/PowerUserAccess",
          "arn:aws:iam::111122223333:policy/github-actions/workload-iam",
          "arn:aws:iam::111122223333:policy/github-actions/guardrails",
        ])
        "gha-${repo}-destroy" = toset([
          "arn:aws:iam::aws:policy/SecurityAudit",
          "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess",
          "arn:aws:iam::111122223333:policy/github-actions/read-extras",
          "arn:aws:iam::111122223333:policy/github-actions/delete",
          "arn:aws:iam::111122223333:policy/github-actions/guardrails",
        ])
      }
    ]...)
    error_message = "Every role must carry the guardrails and the policies of its own tier, and no others."
  }

  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_policy.guardrails.policy).Statement : s.Effect == "Deny"])
    error_message = "The guardrails policy may only deny."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_policy.delete.policy).Statement : [
        for a in flatten([s.Action]) : can(regex("^[a-z0-9-]+:(BatchDelete|CancelSpot|DELETE$|Delete|Deregister|Detach|Disassociate|Release|Remove|RetireGrant$|Revoke|ScheduleKeyDeletion$|Stop|Terminate|Unsubscribe$)", a))
        || a == "route53:ChangeResourceRecordSets"
      ]
    ]))
    error_message = "The destroy roles may only be given actions that remove things."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_policy.read_extras.policy).Statement : alltrue([
        for a in s.Action : can(regex("^[a-z0-9-]+:(BatchGet|Describe|Get|List|Validate)", a))
      ]) if s.Effect == "Allow"
    ])
    error_message = "Read extras may only read."
  }

  assert {
    condition = [
      for s in jsondecode(aws_iam_policy.workload_boundary.policy).Statement : s.Condition.StringEquals["aws:FederatedProvider"]
      if s.Sid == "NotThroughGithub" && s.Effect == "Deny" && s.Action == "*" && s.Resource == "*"
    ] == ["arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"]
    error_message = "A workload role must be useless to anyone who comes in through GitHub."
  }

  assert {
    condition = alltrue([
      for p in [aws_iam_policy.guardrails, aws_iam_policy.workload_boundary] : alltrue([
        for sid in ["NoAccountBillingOrPersonalData", "NoPurchasesOrCommitments", "NoOtherSignIn", "NoRoleChaining"] :
        contains([for s in jsondecode(p.policy).Statement : s.Sid if s.Effect == "Deny"], sid)
      ])
    ])
    error_message = "Pipelines and the workloads they create share the same denies."
  }

  # Everything that can change a flat-rate plan, from AWS's own list of actions.
  assert {
    condition = alltrue([
      for p in [aws_iam_policy.guardrails, aws_iam_policy.workload_boundary] : alltrue([
        for a in ["ApprovePaidSubscription", "AssociateResourcesToSubscription", "CancelSubscription", "CancelSubscriptionChange", "CreateSubscription", "DisassociateResourcesFromSubscription", "UpdateSubscription"] :
        anytrue([
          for s in jsondecode(p.policy).Statement : anytrue([for d in flatten([s.Action]) : can(regex("^${replace(d, "*", ".*")}$", "pricingplanmanager:${a}"))])
          if s.Effect == "Deny" && try(s.Resource, "") == "*" && can(s.Action) && !can(s.Condition)
        ])
      ])
    ])
    error_message = "No pipeline, and nothing that one creates, may change a flat-rate plan."
  }

  # Accepting terms is a person's own decision, for models as for anything that is sold on Marketplace.
  assert {
    condition = alltrue([
      for p in [aws_iam_policy.guardrails, aws_iam_policy.workload_boundary] : alltrue([
        for a in ["aws-marketplace:AcceptAgreementRequest", "aws-marketplace:CreateAgreementRequest", "aws-marketplace:Subscribe", "bedrock:CreateFoundationModelAgreement", "bedrock:PutFoundationModelEntitlement", "bedrock:PutUseCaseForModelAccess"] :
        anytrue([
          for s in jsondecode(p.policy).Statement : anytrue([for d in flatten([s.Action]) : can(regex("^${replace(d, "*", ".*")}$", a))])
          if s.Effect == "Deny" && try(s.Resource, "") == "*" && can(s.Action) && !can(s.Condition)
        ])
      ])
    ])
    error_message = "No pipeline, and nothing that one creates, may accept the terms of a model or of Marketplace."
  }

  # What the look at the site needs, and the AWS policies leave out.
  assert {
    condition = alltrue([
      for a in ["cloudfront:DescribeFunction", "pricingplanmanager:ListSubscriptions", "s3:ListTagsForResource"] :
      contains(flatten([for s in jsondecode(aws_iam_policy.read_extras.policy).Statement : s.Action if s.Effect == "Allow"]), a)
    ])
    error_message = "Plan must be able to look at a site on CloudFront."
  }

  # What Terraform reads of Cloud Map, also while it deletes there.
  assert {
    condition = alltrue([
      for a in ["GetNamespace", "GetOperation", "GetService", "ListInstances", "ListTagsForResource"] :
      contains(flatten([for s in jsondecode(aws_iam_policy.read_extras.policy).Statement : s.Action if s.Effect == "Allow"]), "servicediscovery:${a}")
    ])
    error_message = "Plan and destroy must be able to read the way from an API Gateway to containers."
  }

  assert {
    condition = alltrue([
      for p in [aws_iam_policy.guardrails, aws_iam_policy.read_extras, aws_iam_policy.workload_boundary, aws_iam_policy.workload_iam, aws_iam_policy.delete] : length(p.policy) <= 6144
    ])
    error_message = "A managed policy must stay within 6,144 characters."
  }

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_policy.workload_iam.policy).Statement :
      s.Condition.StringEquals["iam:PermissionsBoundary"] == "arn:aws:iam::111122223333:policy/github-actions/workload-boundary" if s.Sid == "GrantOnlyUnderBoundary"
    ])
    error_message = "Workload roles must be created under the boundary."
  }
}

run "models" {
  command = apply

  # The form of an entry. A name with a wildcard in it would be more than one model.
  assert {
    condition = alltrue([
      for name, m in local.models :
      can(regex("^[a-z0-9-]+$", name))
      && jsonencode(keys(m)) == jsonencode(["aws"])
      && jsonencode(keys(m.aws)) == jsonencode(["model", "profile", "regions"])
      && can(regex("^[a-z0-9]+[.][a-z0-9.:-]+$", m.aws.model))
      && (
        m.aws.profile == null ? jsonencode(m.aws.regions) == jsonencode(["eu-west-2"])
        : m.aws.profile == "eu.${m.aws.model}" ? jsonencode(m.aws.regions) == jsonencode(["eu-*"])
        : m.aws.profile == "global.${m.aws.model}" && jsonencode(m.aws.regions) == jsonencode(["eu-west-2", ""])
      )
    ])
    error_message = "A model in models.json is one model, in London, in Europe or worldwide."
  }

  # Written out again here on purpose, so that a change to models.json fails the test.
  assert {
    condition = jsonencode([for s in jsondecode(aws_iam_policy.workload_boundary.policy).Statement : s if s.Sid == "OnlyListedModels"]) == jsonencode([{
      Sid    = "OnlyListedModels"
      Effect = "Deny"
      Action = "bedrock:Invoke*"
      NotResource = [
        "arn:aws:bedrock:eu-west-2:111122223333:inference-profile/eu.anthropic.claude-haiku-5-5",
        "arn:aws:bedrock:eu-*::foundation-model/anthropic.claude-haiku-5-5",
        "arn:aws:bedrock:eu-west-2:111122223333:project/*",
      ]
    }])
    error_message = "A workload may call the one model in the list, through its European profile, and no other."
  }

  # From AWS's own list of actions: what runs, trains or hosts a model, or signs in with a key.
  assert {
    condition = alltrue([
      for p in [aws_iam_policy.guardrails, aws_iam_policy.workload_boundary] : alltrue([
        for a in [
          "bedrock-mantle:CallWithBearerToken", "bedrock-mantle:CreateCustomizedModel", "bedrock-mantle:CreateFineTuningJob", "bedrock-mantle:CreateInference", "bedrock-mantle:CreateReservation", "bedrock-mantle:UpdateReservation",
          "bedrock:AgenticRetrieveStream", "bedrock:CallWithBearerToken", "bedrock:CreateAdvancedPromptOptimizationJob", "bedrock:CreateCustomModel", "bedrock:CreateCustomModelDeployment", "bedrock:CreateEvaluationJob",
          "bedrock:CreateInferenceProfile", "bedrock:CreateMarketplaceModelEndpoint", "bedrock:CreateModelCopyJob", "bedrock:CreateModelCustomizationJob", "bedrock:CreateModelEvaluationJob", "bedrock:CreateModelImportJob",
          "bedrock:CreateModelInvocationJob", "bedrock:CreatePromptRouter", "bedrock:CreateProvisionedModelThroughput", "bedrock:GenerateQuery", "bedrock:IngestKnowledgeBaseDocuments", "bedrock:OptimizePrompt",
          "bedrock:RegisterMarketplaceModelEndpoint", "bedrock:Rerank", "bedrock:Retrieve", "bedrock:RetrieveAndGenerate", "bedrock:StartAutomatedReasoningPolicyBuildWorkflow", "bedrock:StartAutomatedReasoningPolicyTestWorkflow",
          "bedrock:StartFlowExecution", "bedrock:StartIngestionJob", "bedrock:UpdateCustomModelDeployment", "bedrock:UpdateMarketplaceModelEndpoint", "bedrock:UpdateProvisionedModelThroughput",
        ] :
        anytrue([
          for s in jsondecode(p.policy).Statement : anytrue([for d in flatten([s.Action]) : can(regex("^${replace(d, "*", ".*")}$", a))])
          if s.Effect == "Deny" && try(s.Resource, "") == "*" && can(s.Action) && !can(s.Condition)
        ])
      ])
    ])
    error_message = "No pipeline, and nothing that one creates, may use models in another way than by calling a listed one."
  }

  assert {
    condition = alltrue([
      for a in ["InvokeAgent", "InvokeBuilder", "InvokeDataAutomationAsync", "InvokeFlow", "InvokeInlineAgent", "InvokeModel", "InvokeModelWithResponseStream", "InvokeTool"] :
      anytrue([
        for s in jsondecode(aws_iam_policy.guardrails.policy).Statement : anytrue([for d in flatten([s.Action]) : can(regex("^${replace(d, "*", ".*")}$", "bedrock:${a}"))])
        if s.Effect == "Deny" && try(s.Resource, "") == "*" && can(s.Action) && !can(s.Condition)
      ])
    ])
    error_message = "No pipeline may call a model itself."
  }

  # Otherwise the list would be worth nothing: a workload could call no model at all.
  assert {
    condition = alltrue([
      for a in ["InvokeModel", "InvokeModelWithResponseStream"] : !anytrue([
        for s in jsondecode(aws_iam_policy.workload_boundary.policy).Statement : anytrue([for d in flatten([s.Action]) : can(regex("^${replace(d, "*", ".*")}$", "bedrock:${a}"))])
        if s.Effect == "Deny" && try(s.Resource, "") == "*" && can(s.Action) && !can(s.Condition)
      ])
    ])
    error_message = "A workload must be able to call a listed model."
  }
}

run "cost" {
  command = apply

  assert {
    condition = jsondecode(aws_iam_role.cost.assume_role_policy) == {
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = { Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com" }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = { StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = var.cost_subject
          "token.actions.githubusercontent.com:ref" = "refs/heads/main"
        } }
      }]
    }
    error_message = "The cost role must trust one literal subject, of cloud-labs, in an environment of its own, on main."
  }

  assert {
    condition     = aws_iam_role.cost.name == "gha-cloud-labs-cost" && aws_iam_role.cost.path == "/github-actions/" && aws_iam_role.cost.max_session_duration == 3600
    error_message = "The cost role must lie where the other roles are protected, and end after an hour."
  }

  assert {
    condition = jsondecode(aws_iam_role_policy.cost.policy) == {
      Version = "2012-10-17"
      Statement = [
        { Sid = "ReadCosts", Effect = "Allow", Action = ["ce:GetCostAndUsage"], Resource = "*" },
        { Sid = "NothingElse", Effect = "Deny", NotAction = ["ce:GetCostAndUsage"], Resource = "*" },
      ]
    }
    error_message = "The cost role may ask for costs, and everything else is denied."
  }

  assert {
    condition = (
      aws_iam_role_policy.cost.role == "gha-cloud-labs-cost"
      && !contains([for a in aws_iam_role_policy_attachment.ci : a.role], "gha-cloud-labs-cost")
      && !contains([for p in aws_iam_role_policy.state : p.role], "gha-cloud-labs-cost")
      && !contains(keys(aws_iam_role.ci), "cloud-labs/cost")
    )
    error_message = "The cost role must be no tier: no managed policy and no right to any state."
  }

  # The list that every tier's rights are made from must not know it.
  assert {
    condition     = length(local.identities) == 15 && toset([for id in local.identities : id.tier]) == toset(["plan", "apply", "destroy"])
    error_message = "subjects.json has three tiers. The cost identity stands in cost.json."
  }

  assert {
    condition     = jsondecode(file("../cost.json")) == { cloud-labs = { cost = var.cost_subject } } && contains(output.trusted_subjects, var.cost_subject) && length(output.trusted_subjects) == 16
    error_message = "cost.json holds one subject, and the account trusts that one and the 15."
  }
}

run "state" {
  command = apply

  assert {
    condition = alltrue([
      for key, p in aws_iam_role_policy.state :
      toset(flatten([for s in jsondecode(p.policy).Statement : s.Action])) == toset(
        endswith(key, "/plan") ? ["s3:ListBucket", "s3:GetObject"] : ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      )
    ])
    error_message = "Plan roles may only read state."
  }

  assert {
    condition = alltrue([
      for key, p in aws_iam_role_policy.state : alltrue([
        for s in jsondecode(p.policy).Statement :
        s.Sid == "FindState" ? s.Resource == "arn:aws:s3:::tfstate-0a1b2c3d" : startswith(s.Resource, "arn:aws:s3:::tfstate-0a1b2c3d/${split("/", key)[0]}/")
      ])
    ])
    error_message = "A role may only reach its own repo's state."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls
      && aws_s3_bucket_public_access_block.state.block_public_policy
      && aws_s3_bucket_public_access_block.state.ignore_public_acls
      && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "All four public access blocks must be on."
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "Versioning must be on."
  }

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "Encryption at rest must be on."
  }

  assert {
    condition = (
      alltrue([for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s.Effect == "Deny"])
      && length([for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement : s if startswith(s.Sid, "OnlyOwnState")]) == 5
    )
    error_message = "The bucket policy may only deny, and must isolate each repo."
  }
}

run "github_secrets" {
  command = apply

  assert {
    condition = output.github_secrets == {
      cloud = "aws"
      repos = {
        for repo, id in var.repo_ids : repo => merge({
          repository = {
            AWS_ACCOUNT_ID            = "111122223333"
            AWS_ROLE_ARN              = aws_iam_role.ci["${repo}/plan"].arn
            AWS_STATE_BUCKET          = "tfstate-0a1b2c3d"
            AWS_WORKLOAD_BOUNDARY_ARN = aws_iam_policy.workload_boundary.arn
          }
          production      = { AWS_ROLE_ARN = aws_iam_role.ci["${repo}/apply"].arn }
          nightly-destroy = { AWS_ROLE_ARN = aws_iam_role.ci["${repo}/destroy"].arn }
        }, { for name in ["cost"] : name => { AWS_ROLE_ARN = aws_iam_role.cost.arn } if repo == "cloud-labs" })
      }
    }
    error_message = "Each environment must get its own role, other jobs the plan role, and only cloud-labs the cost role."
  }

  assert {
    condition     = length(distinct(concat([for role in aws_iam_role.ci : role.arn], [aws_iam_role.cost.arn]))) == 16
    error_message = "The comparison above needs 16 different roles."
  }
}

run "rejects_a_wrong_account_id" {
  command         = plan
  expect_failures = [var.account_id]

  variables {
    account_id = "my-account"
  }
}

run "rejects_wildcard_extras" {
  command         = plan
  expect_failures = [var.plan_extra, var.destroy_extra]

  variables {
    plan_extra    = ["s3:*"]
    destroy_extra = ["iam:PutRolePolicy"]
  }
}
