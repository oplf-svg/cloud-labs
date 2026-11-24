# GitHub Actions bootstrap

One Terraform stack per cloud, run once by a person from that cloud's own Cloud Shell. Together they let GitHub Actions
reach AWS, Azure and Google Cloud with short-lived tokens and no stored keys, and give Terraform a place to keep state.

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| How to run it | `run.sh aws`, [runbook](aws/RUNBOOK.md) | `run.sh azure`, [runbook](azure/RUNBOOK.md) | `run.sh gcp`, [runbook](gcp/RUNBOOK.md) |
| Region | `eu-west-2` | `uksouth` | `europe-west2` |
| GitHub is trusted through | an IAM OIDC provider | a federated credential on each identity | a workload identity pool and provider |
| Identities | 15 IAM roles | 15 managed identities | 15 exact subjects, no service accounts |
| State | S3 bucket, one prefix per repo | storage account, one container per repo | Cloud Storage bucket, one prefix per repo |
| Kept apart from what the repos deploy by | IAM paths, denies and the bucket's own policy | a resource group of its own | a project of its own |
| Resources created | 104 | 91 | 45 |

Account, subscription and project ids are inputs at run time. None of them is in this repo. Budgets are not part of
these stacks.

## Identities

Every repo has three. Each one trusts a single, literal OIDC subject, in the form that carries GitHub's permanent
owner and repo ids.

| Tier | Used by | Can do |
|---|---|---|
| `plan` | pull request jobs | Read configuration and its own repo's state |
| `apply` | jobs in the `production` environment, after approval | Deploy, but not administer |
| `destroy` | the nightly job, in the `nightly-destroy` environment | Read configuration, delete, and update its own repo's state |

[subjects.json](subjects.json) is the list that all three stacks read:

```text
repo:oplf-svg@228823995/webhook-platform@1469384538:pull_request
repo:oplf-svg@228823995/webhook-platform@1469384538:environment:production
repo:oplf-svg@228823995/webhook-platform@1469384538:environment:nightly-destroy

repo:oplf-svg@228823995/k8s-platform-lab@1469385215:pull_request
repo:oplf-svg@228823995/k8s-platform-lab@1469385215:environment:production
repo:oplf-svg@228823995/k8s-platform-lab@1469385215:environment:nightly-destroy

repo:oplf-svg@228823995/ai-ops-agent@1469385344:pull_request
repo:oplf-svg@228823995/ai-ops-agent@1469385344:environment:production
repo:oplf-svg@228823995/ai-ops-agent@1469385344:environment:nightly-destroy

repo:oplf-svg@228823995/event-pipeline-lab@1469385472:pull_request
repo:oplf-svg@228823995/event-pipeline-lab@1469385472:environment:production
repo:oplf-svg@228823995/event-pipeline-lab@1469385472:environment:nightly-destroy

repo:oplf-svg@228823995/cloud-labs@1469385611:pull_request
repo:oplf-svg@228823995/cloud-labs@1469385611:environment:production
repo:oplf-svg@228823995/cloud-labs@1469385611:environment:nightly-destroy
```

A plan stops if a subject has a wildcard, the older form without ids, another repo's name, or the wrong ending for its
tier. GitHub never lets a pull request from a fork ask for an OIDC token. A Dependabot pull request can ask, if the
workflow allows it, and gets no more than `plan`.

On AWS and Google Cloud, `apply` and `destroy` must also come from `refs/heads/main`. Azure's exact-match credentials
look only at the issuer, audience and subject, so there the environment's own branch rule is what limits the branch.

### What each tier can do

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| `plan` | `SecurityAudit`, `ViewOnlyAccess` and a few more reads, account-wide | `*/read` on the repo's resource group, minus the known reads of keys, settings, logs and costs | get, list and getIamPolicy on a list of resource types, project-wide |
| `apply` | `PowerUserAccess`, plus IAM roles that must carry a permissions boundary | Contributor on the repo's resource group but not over the group itself, plus grants of 35 named roles to service principals | 31 service roles, plus grants of 10 named roles |
| `destroy` | The `plan` reads, plus delete actions | The `plan` reads, plus `*/delete` on the repo's resource group | The `plan` reads, plus delete on the same types |

No tier can change this trust, hand out administrator rights, touch the state storage or another repo's state, create
sign-in keys or passwords for an identity, buy commitments or read billing data.

## Before the first run

The `nightly-destroy` environment must exist in all five repos first: only `main` can use it, no reviewer, admin bypass
off. If a workflow names an environment that does not exist, GitHub creates it with no rules at all, from any branch.

```bash
python3 scripts/github_checks.py environments
```

This reads GitHub's public API and must print `ok` five times. Every runbook starts with it. GitHub allows 60 anonymous
requests an hour per address and the check uses 20, so if a Cloud Shell is refused, run it on your own computer.

On AWS, not every kind of account can run this: see [Which account](aws/RUNBOOK.md#which-account).

## Secrets in GitHub

[load_secrets.py](scripts/load_secrets.py) stores what each bootstrap printed, as Actions secrets in every repo. They
are ids, kept as secrets so that GitHub hides them in public logs. It hides a value only in jobs that use the secret, so
give every job that talks to a cloud that cloud's ids, for example under `env`.

| | In the repo | In `production` | In `nightly-destroy` |
|---|---|---|---|
| AWS | `AWS_ACCOUNT_ID`, `AWS_ROLE_ARN`, `AWS_STATE_BUCKET`, `AWS_WORKLOAD_BOUNDARY_ARN` | `AWS_ROLE_ARN` | `AWS_ROLE_ARN` |
| Azure | `AZURE_CLIENT_ID`, `AZURE_STATE_ACCOUNT`, `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` | `AZURE_CLIENT_ID` | `AZURE_CLIENT_ID` |
| Google Cloud | `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_STATE_BUCKET`, `GCP_WORKLOAD_IDENTITY_PROVIDER` | | |

A job gets the identity of its environment: `apply` in `production`, `destroy` in `nightly-destroy`, and `plan` anywhere
else.

## Testing the sign-in

[sign-in.yml](../.github/workflows/sign-in.yml) runs on every pull request that changes this folder. It signs in to AWS
and Azure as this repo's `plan`, and [check_sign_in.py](scripts/check_sign_in.py) tries what that identity may and may
not do. It must be able to look around and to read its own state. It must be refused when it creates something, writes
state, or reads what belongs to another repo or to the bootstrap, and on AWS when it asks for another role.

On AWS only a file that exists can show who may open it. S3 says that a file is missing to everyone who may list the
bucket, whatever they may open. So as long as a repo has no state, its line says `nothing there`.

Nothing is changed, even if a right turns out to be too wide: every write is a dry run, a validation, or the replacement
of a file that does not exist. The log is public, so it shows the script's own words and error codes only.

This tests `plan`, the only identity that a pull request can use. `apply` and `destroy` are first used by a repo's own
workflows. Google Cloud is not part of it yet.

## If the nightly destroy stops

GitHub turns off scheduled workflows in a public repo after 60 days without activity, and its documentation does not
say what counts as activity. The schedule can also be dropped on a busy night. Three things catch that:

1. **Before an apply.** The apply job runs `github_checks.py schedules <repo>` before it asks for cloud access, and
   stops if the nightly destroy is off, has never run, failed, or last ran over 36 hours ago, or if `main` has had no
   commit for 50 days. A stack can only be created when its destroy is known to work and has at least ten nights left.
   Other repos get the script by checking out this one at a pinned commit.
2. **Weekly.** The same command without a repo name covers all five.
3. **Budget alerts** on each cloud are the last line. They send email and do not stop spending.

```bash
python3 scripts/github_checks.py schedules
```

## Rules for project code

- **Init** with `-lockfile=readonly`, always. Terraform also installs providers that only the state names, and the
  destroy identity can write state. The lock file needs checksums for every platform it is used on:
  `terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64`.
- **Plan** with `-lock=false`. The plan identity cannot write the lock. Never combine `pull_request_target` with
  `id-token: write`.
- **State** goes under the repo's own name: key `<repo>/...` on AWS, container `<repo>` on Azure, prefix `<repo>/...` on
  Google Cloud. Keep secrets out of state.
- **AWS roles and policies** use `path = "/workload/"`, and roles set `permissions_boundary` to the
  `AWS_WORKLOAD_BOUNDARY_ARN` secret. On EKS use Pod Identity, because pipelines cannot add OIDC providers.
- **Azure resources** go into the existing `rg-<repo>` group, read as data. Set `resource_provider_registrations =
  "none"`, `principal_type = "ServicePrincipal"` on role assignments, and turn off key sign-in where a service has it:
  `plan` cannot read account keys.
- **Google Cloud access** is granted on the resource itself. Only the roles in `grantable_roles` can be granted on the
  project. Set `user_project_override = true` and `billing_project` to the project you deploy into, and use the
  credentials file from the auth action, which renews its ten-minute tokens.
- **Nightly destroy** lives in `.github/workflows/nightly-destroy.yml` and uses the `nightly-destroy` environment. Merge
  it a day before the first apply, so that it has run once.
- **Destroying** needs `terraform state rm` first for things that vanish with their parent but cannot be removed by a
  delete permission: S3 bucket settings, Azure subnet associations, Google Cloud IAM members, node pools and router NAT.
  If that is not enough, pass `destroy_extra` and run the bootstrap again.

## Known limits

- An approved `apply` is trusted with the workloads. Within the limits above it could also leave access behind for
  someone else: an AWS workload role that trusts another account, an Azure identity federated elsewhere, a Google Cloud
  grant to an outside member. Nothing stops that except reading what you approve.
- On AWS, every role can list the names of all files in the state bucket, but can open only its own repo's.
- The repos share one AWS account and one Google Cloud project for what they deploy. There, one repo's `apply` or
  `destroy` can reach another repo's resources, though never its state. On Azure each repo is confined to its own group.
- `plan` sees what a service returns as configuration: environment variables, Cognito client secrets, alarm recipients,
  and on Google Cloud the project's access list, which holds sign-in names. Anyone who can push a branch can run a plan,
  and job logs are public. Keep secrets in a secret store.
- On Google Cloud, `apply` can run workloads as any service account in the project. The [runbook](gcp/RUNBOOK.md) takes
  Editor away from the default one first, and has a check to repeat, because another service may bring its own.
- Keys managed by Microsoft, Amazon and Google encrypt the state. Customer keys would add a fixed monthly cost.
