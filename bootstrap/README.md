# GitHub Actions bootstrap

One Terraform stack per cloud, run once by a person from that cloud's own Cloud Shell. Together they let GitHub Actions
reach AWS, Azure and Google Cloud with short-lived tokens and no stored keys, and give Terraform a place to keep state.

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| How to run it | `run.sh aws`, [runbook](aws/RUNBOOK.md) | `run.sh azure`, [runbook](azure/RUNBOOK.md) | `run.sh gcp`, [runbook](gcp/RUNBOOK.md) |
| Region | `eu-west-2` | `uksouth` | `europe-west2` |
| GitHub is trusted through | an IAM OIDC provider | a federated credential on each identity | a workload identity pool and provider |
| Identities | 16 IAM roles | 16 managed identities | 16 exact subjects, no service accounts |
| State | S3 bucket, one prefix per repo | storage account, one container per repo | Cloud Storage bucket, one prefix per repo |
| Kept apart from what the repos deploy by | IAM paths, denies and the bucket's own policy | a resource group of its own | a project of its own |
| Resources created | 106 | 95 | 50 |

Account, subscription and project ids are inputs at run time. None of them is in this repo. Budgets are not part of
these stacks.

## Identities

Every repo has three. Each one trusts a single, literal OIDC subject, in the form that carries GitHub's permanent
owner and repo ids and ends with the branch.

| Tier | Used by | Can do |
|---|---|---|
| `plan` | jobs in the `plan` environment, without approval | Read configuration and its own repo's state |
| `apply` | jobs in the `production` environment, after approval | Deploy, but not administer |
| `destroy` | the nightly job, in the `nightly-destroy` environment | Read configuration, delete, and update its own repo's state |

GitHub lets only `main` into these environments, and the clouds trust nothing else. So no code gets a cloud token before
a person has approved it into `main`.

`cloud-labs` has one more, in the environment `cost`: it [reads costs and nothing else](#the-identity-that-reads-costs).

[subjects.json](subjects.json) is the list that all three stacks read:

```text
repo:oplf-svg@228823995/webhook-platform@1469384538:environment:plan:ref:refs/heads/main
repo:oplf-svg@228823995/webhook-platform@1469384538:environment:production:ref:refs/heads/main
repo:oplf-svg@228823995/webhook-platform@1469384538:environment:nightly-destroy:ref:refs/heads/main

repo:oplf-svg@228823995/k8s-platform-lab@1469385215:environment:plan:ref:refs/heads/main
repo:oplf-svg@228823995/k8s-platform-lab@1469385215:environment:production:ref:refs/heads/main
repo:oplf-svg@228823995/k8s-platform-lab@1469385215:environment:nightly-destroy:ref:refs/heads/main

repo:oplf-svg@228823995/ai-ops-agent@1469385344:environment:plan:ref:refs/heads/main
repo:oplf-svg@228823995/ai-ops-agent@1469385344:environment:production:ref:refs/heads/main
repo:oplf-svg@228823995/ai-ops-agent@1469385344:environment:nightly-destroy:ref:refs/heads/main

repo:oplf-svg@228823995/event-pipeline-lab@1469385472:environment:plan:ref:refs/heads/main
repo:oplf-svg@228823995/event-pipeline-lab@1469385472:environment:production:ref:refs/heads/main
repo:oplf-svg@228823995/event-pipeline-lab@1469385472:environment:nightly-destroy:ref:refs/heads/main

repo:oplf-svg@228823995/cloud-labs@1469385611:environment:plan:ref:refs/heads/main
repo:oplf-svg@228823995/cloud-labs@1469385611:environment:production:ref:refs/heads/main
repo:oplf-svg@228823995/cloud-labs@1469385611:environment:nightly-destroy:ref:refs/heads/main
```

A plan stops if a subject has a wildcard, the older form without ids, another repo's name, or the wrong ending for its
tier. A pull request from this repo can ask GitHub for an OIDC token, if its workflow says so, but no cloud takes it: its
subject ends in `pull_request` and its own branch, and a job that names an environment does not start, because GitHub
compares the rule for branches with `refs/pull/<number>/merge`.

### The branch at the end

By default, GitHub's subject of a job in an environment does not say which branch the job is from. Azure looks only at
the issuer, audience and subject, so there only the environment's own branch rule would keep other branches out. If that
rule were lost, or GitHub made the environment again without it, any branch could become any of the three.

So each repo has a subject template of its own, `repo`, `context`, `ref`, and every subject ends with the branch. Then
all three clouds compare it exactly, and a lost rule opens nothing. AWS and Google Cloud look at the branch a second
time, as a claim of its own. If the template is lost, GitHub writes a subject that no cloud knows, so everything is
refused and nothing is open. No other template makes a trusted subject out of a token from another branch.

The template belongs to a repo, and only its owner or someone with write access to Actions can set it. This shows it,
for every repo, without a sign-in:

```bash
for r in $(jq -r 'keys[]' subjects.json); do curl -s "https://api.github.com/repos/oplf-svg/$r/actions/oidc/customization/sub"; done
```

### What each tier can do

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| `plan` | `SecurityAudit`, `ViewOnlyAccess` and a few more reads, account-wide | `*/read` on the repo's resource group, minus the known reads of keys, settings, logs and costs | get, list and getIamPolicy on a list of resource types, project-wide |
| `apply` | `PowerUserAccess`, plus IAM roles that must carry a permissions boundary | Contributor on the repo's resource group but not over the group itself, plus grants of 35 named roles to service principals | 31 service roles, plus grants of 10 named roles |
| `destroy` | The `plan` reads, plus delete actions | The `plan` reads, plus `*/delete` on the repo's resource group | The `plan` reads, plus delete on the same types |

No tier can change this trust, hand out administrator rights, touch the state storage or another repo's state, create
sign-in keys or passwords for an identity, buy commitments, accept the terms of a model or of AWS Marketplace, change a
flat-rate plan of CloudFront or read billing data.

On Google Cloud, `destroy` of `cloud-labs` may also search the whole project, so that its night run has a second opinion
about what is left. No other identity may.

### The identity that reads costs

A night run should also say what the day has cost. The three tiers may read no costs at all, so this is for an identity
of its own: only for `cloud-labs`, only on `main`, in the environment `cost`. Its subject stands in
[cost.json](cost.json) and not with the others, because whatever stands there gets a state to write to, and may list the
names of all states.

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| It may | `ce:GetCostAndUsage` | ask Cost Management for a sum | list and read the tables of one dataset |
| Everything else | is denied by its own policy | was never given | was never given |
| What it sees | the costs of this account | the costs of the subscription | what Google's billing export writes: every project of the billing account |

It can read no state, no configuration and no logs, and start nothing. On Azure it has a role of its own, because the
built-in Cost Management Reader may also see every resource group and open support requests. On Google Cloud the export
goes into the bootstrap project, where no pipeline has a project role: in the other one, `apply` may read every dataset
and `destroy` may delete it. The identity has no tier there, so nothing that is given to a tier reaches it.

Costs only arrive after a person has switched them on once: AWS's Cost Explorer in the account that pays, "Azure
charges" in a billing profile if there is one, and Google's billing export into the dataset `billing_export`. Google
fills in no past for a dataset in London. AWS charges 0.01 USD for each question.

## Before the first run

The environments `plan`, `production` and `nightly-destroy` must exist in all five repos first, and `cost` in
`cloud-labs`: only `main` can use them, admin bypass off, and a required reviewer for `production` and for no other. If
a workflow names an environment that does not exist, GitHub creates it with no rules at all, from any branch. Every repo
also needs the subject template from above, `main` must need the check `ci` from everyone, and the repos must be public:
in a private repo of a free account, GitHub ignores the rules of an environment.

```bash
python3 scripts/github_checks.py environments
```

This reads GitHub's public API and must print `ok` five times. Every runbook starts with it. GitHub allows 60 anonymous
requests an hour per address and the check uses 36, so if a Cloud Shell is refused, run it on your own computer.

On AWS, not every kind of account can run this: see [Which account](aws/RUNBOOK.md#which-account).

## On a Mac

Once a Cloud Shell has made everything, `run.sh` also runs on a Mac with Apple silicon, signed in with the clouds' own
tools. There it only carries on what is there: in a wrong account it stops instead of beginning anew.

Whatever runs as a user of a Mac can use that user's sign-in. So it belongs into a user of its own, without administrator
rights, where nothing else runs.

| | |
|---|---|
| `RUN_TMP` | A folder for Terraform that only you can open. Without one, it makes one and removes it at the end |
| `RUN_CHECKED` | A file in a closed folder. If GitHub's side was right, that holds for an hour, for the same check and the same lists. Each look asks 25 questions, and GitHub answers 60 an hour to one address |
| `RUN_RESULTS` | A folder for a file that says how it went: the steps, the numbers of the plan, whether everything matches. No id, no name, nothing that a cloud answered. The folder must be yours alone to change |

## Secrets in GitHub

[load_secrets.py](scripts/load_secrets.py) stores what each bootstrap printed, as Actions secrets in every repo. They
are ids, kept as secrets so that GitHub hides them in public logs. It hides a value only in jobs that use the secret, so
give every job that talks to a cloud that cloud's ids, for example under `env`.

| | In the repo | In `production` | In `nightly-destroy` | In `cost`, only `cloud-labs` |
|---|---|---|---|---|
| AWS | `AWS_ACCOUNT_ID`, `AWS_ROLE_ARN`, `AWS_STATE_BUCKET`, `AWS_WORKLOAD_BOUNDARY_ARN` | `AWS_ROLE_ARN` | `AWS_ROLE_ARN` | `AWS_ROLE_ARN` |
| Azure | `AZURE_CLIENT_ID`, `AZURE_STATE_ACCOUNT`, `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` | `AZURE_CLIENT_ID` | `AZURE_CLIENT_ID` | `AZURE_CLIENT_ID` |
| Google Cloud | `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_STATE_BUCKET`, `GCP_WORKLOAD_IDENTITY_PROVIDER` | | | `GCP_COST_PROJECT_ID` |

A job gets the identity of its environment: `apply` in `production`, `destroy` in `nightly-destroy`, the one that reads
costs in `cost`, and `plan` in `plan`, which has no secrets of its own and gets those of the repo.

## Testing the sign-in

[sign-in.yml](../.github/workflows/sign-in.yml) runs on `main` whenever this folder has changed, and by hand. It signs
in to each cloud as this repo's `plan`, and [check_sign_in.py](scripts/check_sign_in.py) tries what that identity may
and may not do. It must be able to look around and to read its own state. It must be refused when it creates something,
writes state, or reads what belongs to another repo or to the bootstrap, on AWS when it asks for another role, and on
Google Cloud when it wants to act as a service account or change who has access.

On AWS and Google Cloud only a file that exists can show who may open it. Both say that a file is missing to everyone
who may list the bucket, whatever they may open. So as long as a repo has no state, its line says `nothing there`.

Nothing is changed, even if a right turns out to be too wide: every write is a dry run, a validation, a question about a
permission, or the replacement of a file that does not exist. The log is public, so it shows the script's own words and
error codes only.

This tests `plan`. `apply` and `destroy` are first used by a repo's own workflows.
[cost.yml](../.github/workflows/cost.yml) tests the identity that reads costs in the same way, with
[check_cost.py](scripts/check_cost.py): it must be able to ask for a cost, and it must be refused everything else. It
throws the answer away. As long as nobody has switched the costs on, its first question fails, and that is right.

[test_workflows.py](scripts/test_workflows.py) checks, on every pull request, that no workflow of this repo gives a
token to a job outside of the four environments.

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

## The night run of this repo

[nightly-destroy.yml](../.github/workflows/nightly-destroy.yml) runs every night as `destroy`. It starts twice, because
GitHub may drop a start. [night.py](scripts/night.py) signs in, checks that this identity cannot create anything or
become `apply`, and compares the states it finds with [stacks.json](../stacks.json), which names every stack, the clouds
it is on, and what the night does to it: `destroyed`, or `stays` with the reason why. A state that is not in the list
means that something was deployed which nobody declared, and the run fails, so no other stack can be deployed until that
is settled. It looks at the names of the states only: what was made without one, or by hand, is for the budget alerts.

It also looks at GitHub, without any identity ([night_github.py](scripts/night_github.py)): whether the environments
of all five repos, their subject templates and the protection of `main` are still as they should be. That notices a
rule that is gone, and cannot prevent it. It is the only thing that sees a lost reviewer of `production`, because no
token says whether a person has approved. A deploy of the site looks at the same rules of this repo right before it
asks for a token. How many have to approve a pull request, GitHub shows to administrators only, so nothing here can
look at that.

## Rules for project code

- **Init** with `-lockfile=readonly`, always. Terraform also installs providers that only the state names, and the
  destroy identity can write state. The lock file needs checksums for every platform it is used on:
  `terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64`.
- **Plan** on `main`, in the `plan` environment, with `-lock=false`: the plan identity cannot write the lock. A pull
  request cannot be planned, so read the plan before you approve the apply. Give `id-token: write` only to jobs in one of
  the environments, and never in a workflow that `pull_request_target` or `workflow_run` starts.
- **State** goes under the repo's own name: key `<repo>/...` on AWS, container `<repo>` on Azure, prefix `<repo>/...` on
  Google Cloud. Keep secrets out of state.
- **AWS roles and policies** use `path = "/workload/"`, and roles set `permissions_boundary` to the
  `AWS_WORKLOAD_BOUNDARY_ARN` secret. On EKS use Pod Identity, because pipelines cannot add OIDC providers.
- **Azure resources** go into the existing `rg-<repo>` group, read as data. Set `resource_provider_registrations =
  "none"`, `principal_type = "ServicePrincipal"` on role assignments, and turn off key sign-in where a service has it:
  `plan` cannot read account keys. Terraform writes an empty state on Azure as soon as it finds none, which `plan` may
  not do, so plan the very first time without the backend, as [deploy.py](../site/deploy/deploy.py) does.
- **Google Cloud access** is granted on the resource itself. Only the roles in `grantable_roles` can be granted on the
  project. Set `user_project_override = true` and `billing_project` to the project you deploy into, and use the
  credentials file from the auth action, which renews its ten-minute tokens.
- **Nightly destroy** lives in `.github/workflows/nightly-destroy.yml` and uses the `nightly-destroy` environment. Merge
  it a day before the first apply, so that it has run once.
- **Destroying** needs `terraform state rm` first for things that vanish with their parent but cannot be removed by a
  delete permission: S3 bucket settings, Azure subnet associations, Google Cloud IAM members, node pools and router NAT.
  If that is not enough, pass `destroy_extra` and run the bootstrap again.

## The agents' identity

Coding agents do not use a person's GitHub sign-in. They work as a GitHub App, through
[as_agent.py](scripts/as_agent.py), which gets a token for one repo and one hour at most, gives it to one command, and
prints neither the token nor the App's key.

| The App may | It may not |
|---|---|
| Push branches and open pull requests | Change workflow files, settings, rules, environments or secrets |
| Read checks and runs | Approve a deployment |
| Merge what a person has approved | Approve its own pull request |

`main` needs one approval from someone other than whoever pushed last, and a new push cancels earlier approvals. So a
change to a workflow file has to be pushed by a person, and everything an agent proposes has to be approved by one.
Suspending the App stops every agent at once.

This holds only where agents run without a person's sign-in: no `gh` login, no GitHub credential in another program, and
no signed-in browser that an agent can drive.

## Known limits

- An approved `apply` is trusted with the workloads. Within the limits above it could also leave access behind for
  someone else: an AWS workload role that trusts another account, an Azure identity federated elsewhere, a Google Cloud
  grant to an outside member. Nothing stops that except reading what you approve.
- On AWS and Google Cloud, every identity of the three tiers can list the names of all files in the state bucket, but
  can open only its own repo's.
- The repos share one AWS account and one Google Cloud project for what they deploy. There, one repo's `apply` or
  `destroy` can reach another repo's resources, though never its state. On Azure each repo is confined to its own group.
- Whoever may search on Google Cloud sees the configuration of everything in the project. That is `destroy` of
  `cloud-labs`.
- Everything rests on `main`. If its protection were lost, whoever may push to it could become `plan`, `destroy` and the
  identity that reads costs, but not `apply`, which still asks a person. The night run notices it.
- `plan` sees what a service returns as configuration: environment variables, Cognito client secrets, alarm recipients,
  and on Google Cloud the project's access list, which holds sign-in names. What is on `main` can print it, and job logs
  are public. Keep secrets in a secret store.
- On Google Cloud, `apply` can run workloads as any service account in the project. The [runbook](gcp/RUNBOOK.md) takes
  Editor away from the default one first, and has a check to repeat, because another service may bring its own.
- Keys managed by Microsoft, Amazon and Google encrypt the state. Customer keys would add a fixed monthly cost.
