# The site

A static site in English, Spanish and French, served by AWS and by Azure from the same build. Its recorder plays back
real test runs and exists twice, in React and in Angular. Both builds share one core without a framework and have to pass
the same browser tests.

| Folder | What it holds |
|---|---|
| `pages` | The pages (Astro), and their words in `src/text` |
| `packages/core` | The recorder's data, drawing and player, its look, and the real runs in `data/runs.json` |
| `packages/recorder-react`, `packages/recorder-angular` | The two builds, each a custom element |
| `scripts` | `import-runs.mjs` fetches the public logs of the sign-in test, `collect-builds.mjs` measures the builds |
| `e2e` | The browser tests |
| `infra/aws`, `infra/azure` | One small Terraform stack per cloud |
| `deploy` | How it is built, deployed and checked |

```bash
npm ci             # in this folder
npm run dev        # both recorders, then the pages, at http://localhost:4321
./checks.sh        # everything that CI runs. Needs Chrome, and the Terraform that bootstrap/scripts installs
```

Rules: real recordings link to their run, examples are marked as examples, nothing counts as proven without a public
test, and no text may hold a name, an account or an address. `npm test` checks what it can of that.

## Where it runs

| | AWS | Azure |
|---|---|---|
| Served by | CloudFront, from a private S3 bucket in London | Static Web Apps, settings in West Europe |
| Plan | Free flat-rate plan: no overage charges | Free plan: overage cannot be bought |
| When the allowance is used up | AWS may slow it down | It stops until the next month |
| A flood of made-up addresses | [edge.js](infra/aws/edge.js) turns them all into one, which CloudFront keeps, so the storage is asked about it once a day per place | Counts towards the allowance |
| Headers and file types | AWS's own security headers policy | [staticwebapp.config.json](deploy/staticwebapp.config.json) |

It stays on at night, as [stacks.json](../stacks.json) says. It has no forms, no sign-in, no cookies, no server and no
secrets. `/files.txt` lists every file with its SHA-256, so anyone can compare what they get:
`curl -s https://HOST/files.txt`.

Requests to the storage are not part of CloudFront's plan. What visitors ask for is kept at the edge until the next
deploy, so there are few of them, and the budget alert is the last line.

## How a change goes live

1. A pull request runs `checks.sh`. `site.yml` gives a pull request no access to a cloud.
2. A person approves and merges it. [site.yml](../.github/workflows/site.yml) builds it once.
3. It looks at both clouds, as an identity that can do nothing else, so nobody has to approve that. The looks say what
   would change, in the stacks and in the files.
4. A person approves the deploy to Azure, and then the one to AWS. A deploy stops unless it is the same run, the same
   plan, the same files and the same starting point that its look has shown. It also stops if the plan would delete or
   replace something, if there is a newer version on `main`, or if the last night run did not succeed.
5. It then asks for every address as a visitor would, and fails unless the bytes are those that were built, the security
   headers are there, no cookie is set, there is nothing to sign in to, and an address that does not exist gets a 404.

[deploy.py](deploy/deploy.py) does this, and [its tests](deploy/test_deploy.py) run against stand-ins for both clouds.
The very first deploy has to wait until the night run has succeeded once on its schedule.

## The first deploy to AWS

The distribution is created switched off, because without the plan a flood of requests would cost money. Pipelines may
not subscribe to anything, so a person does it once:

1. In an account made with **Sign up for AWS (new)**, AWS's own policy denies the plan's API. In the management account,
   open **AWS Organizations**, **Policies**, **Service control policies**, and add `pricingplanmanager:CreateSubscription`,
   `pricingplanmanager:GetSubscription` and `pricingplanmanager:ListSubscriptions` to the statement `UsEast1Partitional` of
   `AdvancedModeRegionRestrictionSecurityControlPolicy`. Add no others: without them nobody in the account can move the
   site to a plan that costs money. Until this is done, the look at AWS stops and says so.
2. Deploy, then open the distribution `cloud-labs site` in the CloudFront console and choose the **Free** plan. Keep the
   protections that it offers.
3. When the plan is active, start the workflow `site` on `main` by hand. The look says `enabled`, and after the deploy the
   site is public.

If AWS says that the account has to be verified first, or that it cannot have a plan, the site stays off there and costs
nothing. The same workflow switches it off again if it ever leaves the plan.

## Taking it down

The pipelines never delete it. On Azure, delete the static web app `cloud-labs-site` in the resource group
`rg-cloud-labs`. On AWS, in this order, so that it is never on without the plan:

1. Disable the distribution.
2. Cancel the plan. In the kind of account above, add `pricingplanmanager:CancelSubscription` to the same statement first.
3. Delete the distribution, and the firewall (web ACL) that came with the plan, which costs money without it.
4. Empty and delete the bucket that starts with `cloud-labs-site-`.

Take `site` out of `stacks.json` last, and delete its two states.
