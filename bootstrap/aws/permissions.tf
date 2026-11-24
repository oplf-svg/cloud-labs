locals {
  # AWS keeps the first two to configuration and metadata, with a few exceptions that read_extras
  # denies. Plan and destroy both need them to refresh state.
  read_policies = {
    security-audit = "arn:aws:iam::aws:policy/SecurityAudit"
    view-only      = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
    read-extras    = aws_iam_policy.read_extras.arn
  }

  tier_policies = {
    plan = merge(local.read_policies, {
      guardrails = aws_iam_policy.guardrails.arn
    })
    apply = merge(
      {
        power-user   = "arn:aws:iam::aws:policy/PowerUserAccess"
        workload-iam = aws_iam_policy.workload_iam.arn
        guardrails   = aws_iam_policy.guardrails.arn
      },
      { for i, arn in var.apply_extra : "extra-${i}" => arn },
    )
    destroy = merge(local.read_policies, {
      delete     = aws_iam_policy.delete.arn
      guardrails = aws_iam_policy.guardrails.arn
    })
  }

  attachments = merge([
    for key, id in local.identities : {
      for name, arn in local.tier_policies[id.tier] : "${key}/${name}" => {
        identity   = key
        policy_arn = arn
      }
    }
  ]...)

  # Service => actions that remove things. Nothing in this list creates or changes a resource.
  delete_actions = {
    acm                     = ["Delete*"]
    aoss                    = ["Delete*"]
    apigateway              = ["DELETE"]
    application-autoscaling = ["Delete*", "Deregister*"]
    athena                  = ["Delete*", "Stop*"]
    autoscaling             = ["BatchDelete*", "Delete*", "Detach*", "Terminate*"]
    bedrock                 = ["Delete*", "Disassociate*"]
    bedrock-agentcore       = ["Delete*"]
    cloudfront              = ["Delete*"]
    cloudwatch              = ["Delete*"]
    cognito-identity        = ["Delete*"]
    cognito-idp             = ["Delete*"]
    dynamodb                = ["DeleteResourcePolicy", "DeleteTable", "DeleteTableReplica"]
    ec2                     = ["CancelSpot*", "Delete*", "Deregister*", "Detach*", "Disassociate*", "Release*", "Revoke*", "Terminate*"]
    ecr                     = ["BatchDelete*", "Delete*"]
    ecs                     = ["Delete*", "Deregister*", "StopTask"]
    eks                     = ["Delete*", "Deregister*", "Disassociate*"]
    elasticache             = ["Delete*"]
    elasticfilesystem       = ["Delete*"]
    elasticloadbalancing    = ["Delete*", "Deregister*", "Remove*"]
    es                      = ["Delete*"]
    events                  = ["Delete*", "Remove*"]
    firehose                = ["Delete*"]
    glue                    = ["BatchDelete*", "Delete*", "Stop*"]
    kafka                   = ["Delete*"]
    kinesis                 = ["Delete*", "Deregister*"]
    kinesisanalytics        = ["Delete*", "Stop*"]
    kms                     = ["DeleteAlias", "RetireGrant", "RevokeGrant", "ScheduleKeyDeletion"]
    lambda                  = ["Delete*", "Remove*"]
    logs                    = ["Delete*", "Disassociate*"]
    pipes                   = ["Delete*", "Stop*"]
    rds                     = ["Delete*", "Deregister*", "Remove*"]
    resource-groups         = ["Delete*"]
    route53                 = ["Delete*", "Disassociate*"]
    s3                      = ["DeleteBucket", "DeleteBucketPolicy", "DeleteBucketWebsite", "DeleteObject", "DeleteObjectVersion"]
    s3vectors               = ["Delete*"]
    scheduler               = ["Delete*"]
    schemas                 = ["Delete*"]
    secretsmanager          = ["Delete*", "Remove*"]
    servicediscovery        = ["Delete*", "Deregister*"]
    sns                     = ["Delete*", "Remove*", "Unsubscribe"]
    sqs                     = ["DeleteQueue", "RemovePermission"]
    ssm                     = ["Delete*"]
    states                  = ["Delete*", "Stop*"]
    synthetics              = ["Delete*", "Stop*"]
    wafv2                   = ["Delete*", "Disassociate*"]
    xray                    = ["Delete*"]
  }

  delete_action_list = concat(
    flatten([for service, actions in local.delete_actions : [for a in actions : "${service}:${a}"]]),
    var.destroy_extra,
  )
  # Job logs are public. Keep contact, billing, sign-in and user data out of reach.
  account_data_actions = [
    "account:*",
    "account-access:*",
    "aws-portal:*",
    "billing:*",
    "budgets:*",
    "ce:*",
    "cloudtrail:LookupEvents",
    "cognito-idp:AdminGetUser",
    "cognito-idp:ListUsers*",
    "consolidatedbilling:*",
    "cur:*",
    "freetier:*",
    "iam:GenerateCredentialReport",
    "iam:GetAccountAuthorizationDetails",
    "iam:GetCredentialReport",
    "iam:GetUser*",
    "iam:ListAccessKeys",
    "iam:ListUsers",
    "iam:ListVirtualMFADevices",
    "identitystore:*",
    "invoicing:*",
    "mq:ListUsers",
    "notifications-contacts:*",
    "organizations:*",
    "payments:*",
    "purchase-orders:*",
    "sso:*",
    "sso-directory:*",
    "support:*",
    "supportplans:*",
    "tax:*",
    "user-subscriptions:*",
  ]

  # Azure and Google Cloud apply identities cannot buy commitments either.
  purchase_actions = [
    "artifact:AcceptAgreement",
    "athena:CreateCapacityReservation",
    "aws-marketplace:AcceptAgreement*",
    "bedrock-mantle:CreateReservation",
    "bedrock:CreateProvisionedModelThroughput",
    "cloudfront:CreateSavingsPlan",
    "devicefarm:PurchaseOffering",
    "devicefarm:RenewOffering",
    "dynamodb:PurchaseReservedCapacityOfferings",
    "ec2:AcceptReservedInstancesExchangeQuote",
    "ec2:CreateCapacityReservation*",
    "ec2:Purchase*",
    "eks:CreateEksAnywhereSubscription",
    "elasticache:Purchase*",
    "elemental-appliances-software:CreateOrderV1",
    "es:Purchase*",
    "glacier:PurchaseProvisionedCapacity",
    "license-manager-user-subscriptions:StartProductSubscription",
    "mediaconnect:PurchaseOffering",
    "medialive:PurchaseOffering",
    "memorydb:Purchase*",
    "outposts:CreateOrder",
    # CloudFront's flat-rate plans. Cancelling the free one brings back charges by use, and an update can
    # move a distribution to a plan of up to 10,000 USD a month.
    "pricingplanmanager:Approve*",
    "pricingplanmanager:Associate*",
    "pricingplanmanager:Cancel*",
    "pricingplanmanager:Create*",
    "pricingplanmanager:Disassociate*",
    "pricingplanmanager:Update*",
    "qbusiness:CreateSubscription",
    "quicksight:CreateAccountSubscription",
    "rds:CreateDBCapacityReservation",
    "rds:Purchase*",
    "redshift-serverless:CreateReservation",
    "redshift:AcceptReservedNodeExchange",
    "redshift:Purchase*",
    "route53domains:RegisterDomain",
    "route53domains:RenewDomain",
    "route53domains:TransferDomain*",
    "sagemaker:CreateReservedCapacity",
    "sagemaker:CreateTrainingPlan",
    "savingsplans:CreateSavingsPlan",
    "shield:CreateSubscription",
  ]

  # A second way in, with certificates instead of GitHub.
  sign_in_actions = ["rolesanywhere:*"]

  shared_denies = [
    {
      Sid      = "NoAccountBillingOrPersonalData"
      Effect   = "Deny"
      Action   = local.account_data_actions
      Resource = "*"
    },
    {
      Sid      = "NoPurchasesOrCommitments"
      Effect   = "Deny"
      Action   = local.purchase_actions
      Resource = "*"
    },
    {
      Sid      = "NoOtherSignIn"
      Effect   = "Deny"
      Action   = local.sign_in_actions
      Resource = "*"
    },
  ]
}

# Attached to all 15 roles. Contains only denies.
resource "aws_iam_policy" "guardrails" {
  name        = "guardrails"
  path        = local.ci_path
  description = "Denies that apply to every GitHub Actions role."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        # No role may change the trust, use another CI role, or edit these policies.
        Sid       = "ProtectGithubTrust"
        Effect    = "Deny"
        NotAction = ["iam:Get*", "iam:List*"]
        Resource  = [local.oidc_provider_arn, local.ci_roles, local.ci_policies]
      },
      {
        # Pipelines never use another role, such as an admin role that trusts the whole account.
        Sid         = "NoRoleChaining"
        Effect      = "Deny"
        Action      = ["sts:AssumeRole", "sts:AssumeRoot"]
        NotResource = local.workload_roles
      },
      {
        Sid    = "NoLongLivedCredentials"
        Effect = "Deny"
        Action = [
          "iam:CreateAccessKey",
          "iam:CreateLoginProfile",
          "iam:CreateOpenIDConnectProvider",
          "iam:CreateSAMLProvider",
          "iam:CreateServiceSpecificCredential",
          "iam:CreateUser",
          "iam:UpdateLoginProfile",
          "iam:UploadSigningCertificate",
          "iam:UploadSSHPublicKey",
        ]
        Resource = "*"
      },
    ], local.shared_denies)
  })
}

# Reads Terraform needs that SecurityAudit and ViewOnlyAccess leave out.
resource "aws_iam_policy" "read_extras" {
  name        = "read-extras"
  path        = local.ci_path
  description = "Configuration reads for the plan and destroy roles."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadConfiguration"
        Effect = "Allow"
        Action = concat([
          "aoss:BatchGetCollection",
          "aoss:GetAccessPolicy",
          "aoss:GetSecurityPolicy",
          "application-autoscaling:ListTagsForResource",
          "cloudfront:DescribeFunction",
          "cognito-idp:GetUserPoolMfaConfig",
          "glue:GetCrawler",
          "glue:GetDatabase",
          "glue:GetJob",
          "lambda:GetEventSourceMapping",
          "lambda:GetFunction",
          "pipes:DescribePipe",
          "pricingplanmanager:ListSubscriptions",
          "s3:ListBucketVersions",
          "s3:ListTagsForResource",
          "scheduler:GetSchedule",
          "scheduler:GetScheduleGroup",
          "servicediscovery:GetNamespace",
          "states:ValidateStateMachineDefinition",
        ], var.plan_extra)
        Resource = "*"
      },
      {
        # AWS's own public parameters, such as the latest AMI ids.
        Sid      = "ReadPublicParameters"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:*::parameter/aws/service/*"
      },
      {
        # Contents that the two AWS policies return in spite of their purpose.
        Sid    = "NoContents"
        Effect = "Deny"
        Action = [
          "backup-search:*",
          "cleanrooms:GetProtectedQuery",
          "cognito-sync:*",
          "rds:DownloadDBLogFilePortion",
          "s3vectors:GetVectors",
          "security-ir:*",
        ]
        Resource = "*"
      },
    ]
  })
}

# The most any role created by a project can ever do.
resource "aws_iam_policy" "workload_boundary" {
  name        = "workload-boundary"
  path        = local.ci_path
  description = "Permissions boundary that every role created by GitHub Actions must carry."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "ServicesButNotIdentity"
        Effect    = "Allow"
        NotAction = ["iam:*"]
        Resource  = "*"
      },
      {
        Sid    = "IdentityReadsServicesNeed"
        Effect = "Allow"
        Action = [
          "iam:CreateServiceLinkedRole",
          "iam:GetInstanceProfile",
          "iam:GetRole",
          "iam:ListInstanceProfiles",
        ]
        Resource = "*"
      },
      {
        Sid      = "PassWorkloadRolesOnly"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = local.workload_roles
      },
      {
        # EKS creates its own node instance profiles.
        Sid    = "EksInstanceProfiles"
        Effect = "Allow"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
        ]
        Resource = local.eks_instance_profile
      },
      {
        Sid      = "NoTerraformState"
        Effect   = "Deny"
        Action   = "s3:*"
        Resource = [local.bucket_arn, "${local.bucket_arn}/*"]
      },
      {
        # IAM cannot check whom a new role trusts. A workload role that trusts GitHub gets nothing.
        Sid       = "NotThroughGithub"
        Effect    = "Deny"
        Action    = "*"
        Resource  = "*"
        Condition = { StringEquals = { "aws:FederatedProvider" = local.oidc_provider_arn } }
      },
      {
        Sid         = "NoRoleChaining"
        Effect      = "Deny"
        Action      = ["sts:AssumeRole", "sts:AssumeRoot"]
        NotResource = local.workload_roles
      },
    ], local.shared_denies)
  })
}

# PowerUserAccess has no IAM rights. This adds roles for workloads, under the boundary only.
resource "aws_iam_policy" "workload_iam" {
  name        = "workload-iam"
  path        = local.ci_path
  description = "Lets the apply roles manage workload roles, always under the permissions boundary."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadIdentities"
        Effect = "Allow"
        Action = [
          "iam:GetInstanceProfile",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListEntitiesForPolicy",
          "iam:ListInstanceProfiles",
          "iam:ListInstanceProfilesForRole",
          "iam:ListInstanceProfileTags",
          "iam:ListPolicies",
          "iam:ListPolicyTags",
          "iam:ListPolicyVersions",
          "iam:ListRolePolicies",
          "iam:ListRoles",
          "iam:ListRoleTags",
        ]
        Resource = "*"
      },
      {
        Sid    = "GrantOnlyUnderBoundary"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:CreateRole",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy",
          "iam:PutRolePermissionsBoundary",
          "iam:PutRolePolicy",
        ]
        Resource  = local.workload_roles
        Condition = { StringEquals = { "iam:PermissionsBoundary" = local.workload_boundary } }
      },
      {
        Sid    = "ManageWorkloadRoles"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:PassRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:UpdateRole",
          "iam:UpdateRoleDescription",
        ]
        Resource = local.workload_roles
      },
      {
        Sid    = "ManageWorkloadPolicies"
        Effect = "Allow"
        Action = [
          "iam:CreatePolicy",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:SetDefaultPolicyVersion",
          "iam:TagPolicy",
          "iam:UntagPolicy",
        ]
        Resource = local.workload_policies
      },
      {
        Sid    = "ManageWorkloadInstanceProfiles"
        Effect = "Allow"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile",
        ]
        Resource = local.workload_profiles
      },
    ]
  })
}

# Delete-only. The destroy roles get this plus the read policies, and nothing that creates.
resource "aws_iam_policy" "delete" {
  name        = "delete"
  path        = local.ci_path
  description = "Delete actions for the nightly destroy roles."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DeleteResources"
        Effect   = "Allow"
        Action   = local.delete_action_list
        Resource = "*"
      },
      {
        Sid    = "DeleteWorkloadIdentities"
        Effect = "Allow"
        Action = [
          "iam:DeleteInstanceProfile",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:DeleteRole",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy",
          "iam:RemoveRoleFromInstanceProfile",
        ]
        Resource = [local.workload_roles, local.workload_policies, local.workload_profiles]
      },
      {
        # Route 53 has one action for adding and removing records. Allow it for removals only.
        Sid      = "DeleteDnsRecords"
        Effect   = "Allow"
        Action   = "route53:ChangeResourceRecordSets"
        Resource = "arn:aws:route53:::hostedzone/*"
        Condition = {
          "ForAllValues:StringEquals" = { "route53:ChangeResourceRecordSetsActions" = ["DELETE"] }
          "Null"                      = { "route53:ChangeResourceRecordSetsActions" = "false" }
        }
      },
    ]
  })
}
