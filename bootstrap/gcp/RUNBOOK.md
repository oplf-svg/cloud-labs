# Google Cloud runbook

Run once, as Owner of both projects, in Cloud Shell. Nothing here needs a key, and GitHub plays no part in it.

| You run | It creates | Where | Cost |
|---|---|---|---|
| `terraform apply`, once | 1 workload identity pool and provider | bootstrap project | Free |
| | 1 Cloud Storage bucket for state: encrypted, versioned, public access blocked | bootstrap project | Under 0.05 USD a month |
| | 1 empty BigQuery dataset for Google's billing export, 1 custom role on it | bootstrap project | Free until 10 GB |
| | 5 custom roles, 38 project grants | the project the repos deploy into | Free |

You need two projects: the one the repos deploy into, and one that holds only the trust and the state. Some of Google's
own service agents can read every bucket in their project and run code for whoever asks, and a bucket cannot refuse
them. A project is free.

## The short way

Open the Google Cloud console and start **Cloud Shell**. Both projects have to exist first, see step 4. This does every
step below. It shows the plan and asks before it creates anything, and it can be run again if it stops.

```bash
[ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs; git -C ~/cloud-labs pull --ff-only && ~/cloud-labs/bootstrap/scripts/run.sh gcp
```

It asks for the two project ids.

Then follow [Hand it to GitHub](#hand-it-to-github). The rest of this page is for checking, changing and undoing it, or
for doing it by hand.

## Run it by hand

1. Open the Google Cloud console and start **Cloud Shell**. Allow it to use your account if it asks.

2. Get the code. Check that the commit shown is the one you reviewed.

   ```bash
   [ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs
   cd ~/cloud-labs/bootstrap/gcp && git pull --ff-only && git log -1 --format='%H %s'
   ```

3. Check the GitHub side. Stop unless all five repos print `ok`.

   ```bash
   python3 ../scripts/github_checks.py environments
   ```

4. Set both project ids, with yours in place of `PROJECT_ID` and `BOOTSTRAP_PROJECT_ID`.

   ```bash
   export TF_VAR_project_id=PROJECT_ID TF_VAR_bootstrap_project_id=BOOTSTRAP_PROJECT_ID
   ```

   If the bootstrap project does not exist yet, create it and link it to your billing account. The first line shows the
   account's id, to put in place of `BILLING_ID`.

   ```bash
   gcloud billing accounts list
   ```

   ```bash
   gcloud projects create "$TF_VAR_bootstrap_project_id" && gcloud billing projects link "$TF_VAR_bootstrap_project_id" --billing-account=BILLING_ID
   ```

   This must print `True` twice.

   ```bash
   for p in "$TF_VAR_project_id" "$TF_VAR_bootstrap_project_id"; do gcloud billing projects describe "$p" --format='value(billingEnabled)'; done
   ```

5. Turn on the APIs, and get Terraform.

   ```bash
   gcloud services enable bigquery.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com storage.googleapis.com sts.googleapis.com --project "$TF_VAR_bootstrap_project_id"
   gcloud services enable cloudasset.googleapis.com cloudresourcemanager.googleapis.com compute.googleapis.com iam.googleapis.com serviceusage.googleapis.com --project "$TF_VAR_project_id"
   ```

   ```bash
   ../scripts/install-terraform.sh /tmp/tf-bin
   export PATH=/tmp/tf-bin:$PATH TF_DATA_DIR=/tmp/tf-gcp
   ```

6. Turning on Compute Engine created a default service account. In a project without an organization it gets the Editor
   role, and pipelines could run workloads as it, so take the role away. If it says `not found`, wait a minute and run
   the check for Editor under "Check it".

   ```bash
   gcloud projects remove-iam-policy-binding "$TF_VAR_project_id" --condition=None --role=roles/editor --member="serviceAccount:$(gcloud projects describe "$TF_VAR_project_id" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
   ```

   It also created a network called `default` that lets SSH and RDP in from the whole internet. Nothing is reachable
   until a machine is put in it. In a project that had no Compute Engine before, you can delete it:

   ```bash
   gcloud compute firewall-rules list --project "$TF_VAR_project_id" --filter='network~/default$' --format='value(name)' | xargs -r gcloud compute firewall-rules delete --project "$TF_VAR_project_id" --quiet
   gcloud compute networks delete default --project "$TF_VAR_project_id"
   ```

7. Plan. It must end with `Plan: 51 to add, 0 to change, 0 to destroy.` If an API says it is not enabled yet, wait a
   minute and try again.

   ```bash
   terraform init -lockfile=readonly && terraform plan -out=tfplan
   ```

8. Apply, and move the state into the new bucket straight away.

   ```bash
   terraform apply tfplan && terraform output -raw backend_tf > backend.tf && terraform init -lockfile=readonly -migrate-state -force-copy
   ```

   If the apply stops halfway, for example because the new pool is not known everywhere yet, keep the shell open, wait a
   minute and repeat from `terraform plan -out=tfplan` in step 7. What exists already is not created twice, so the
   number is smaller.

9. Check that the state is in the bucket, then remove the local copy. The count must be 52.

   ```bash
   terraform state list | wc -l
   ```

   ```bash
   rm -f terraform.tfstate terraform.tfstate.backup tfplan && terraform plan
   ```

   The plan must say `No changes`.

## Check it

Every subject Google Cloud trusts, against the two lists in this repo:

```bash
diff <(jq -r '.[][]' ../subjects.json ../cost.json | sort) <(gcloud iam workload-identity-pools providers describe github --workload-identity-pool=github-actions --location=global --project "$TF_VAR_bootstrap_project_id" --format='value(attributeCondition)' | grep -o 'repo:[^"]*' | sort) && echo "16 subjects match"
```

The bucket: public access prevention `enforced`, uniform access and versioning `true`. In the access list, the only
members are the bootstrap project's owner and principals from the `github-actions` pool.

```bash
B=$(terraform output -raw state_bucket); gcloud storage buckets describe "gs://$B" --format='yaml(public_access_prevention, uniform_bucket_level_access, versioning_enabled, soft_delete_policy)'; gcloud storage buckets get-iam-policy "gs://$B" --format='value(bindings.members)'
```

Nobody runs workloads as Editor. The only service account this may list ends in `@cloudservices.gserviceaccount.com`,
which belongs to Google and cannot be used by a workload. Take Editor away from any other, as in step 6. Look again
after a repo turns on a new Google service: App Engine, for one, brings an account ending in
`@appspot.gserviceaccount.com`.

```bash
gcloud projects get-iam-policy "$TF_VAR_project_id" --flatten='bindings[].members' --filter='bindings.role=roles/editor' --format='value(bindings.members)'
```

## Hand it to GitHub

This prints what the repos need: ids and names, no passwords. Copy all of it. `run.sh` prints it too.

```bash
terraform output -json github_secrets | fold -w 100; echo
```

On your own computer, in your clone of this repo, with that in the clipboard:

```bash
pbpaste | python3 bootstrap/scripts/load_secrets.py
```

It checks every value, lists the names it will set, never shows a value, and asks before it writes.

## Costs

Google writes costs only where you tell it to, and fills in no past for a dataset in London. So switch it on before the
first stack: in the console, **Billing**, **Billing export**, **BigQuery export**, **Standard usage cost**, with the
bootstrap project and the dataset `billing_export`. Google makes its own export account an owner of the dataset. Leave
that there, or the export stops and nobody is told. The first rows take some hours. They hold the costs of every project
on the billing account.

## Run it again later

`run.sh` carries out what has changed here since, for example in [subjects.json](../subjects.json). It shows the plan,
asks, and stops if something would be deleted or replaced. Everything that a new subject or a new permission touches
changes in place. Google takes some minutes to use a changed provider everywhere. It passes no variables and takes back
what one of them had added, so first export every variable you ever set, as in `export TF_VAR_destroy_extra='["..."]'`.

By hand, for example to pass `-var 'destroy_extra=["..."]'`: pass every variable you ever set, each time, because
leaving one out undoes it. Do steps 2 to 5, then:

```bash
B=$(gcloud storage buckets list --project "$TF_VAR_bootstrap_project_id" --filter='name~^tfstate-' --format='value(name)' | head -1)
printf 'terraform {\n  backend "gcs" {}\n}\n' > backend.tf
terraform init -lockfile=readonly -backend-config="bucket=$B" -backend-config=prefix=bootstrap
terraform plan
```

## Undo it

Destroy every repo's own stacks first. Once the pool is gone, GitHub cannot.

1. Do "Run it again later", so that Terraform has the state.

2. Switch the billing export off in the console and delete the tables in the dataset `billing_export`: Terraform deletes
   it only when it is empty. Then bring the state back to Cloud Shell and allow the bucket and the dataset to be
   deleted. The last line leaves the bucket's access list in place until the bucket itself goes, because it is what
   gives you access to the contents.

   ```bash
   rm backend.tf && terraform init -lockfile=readonly -migrate-state -force-copy
   sed -i 's/prevent_destroy = true/prevent_destroy = false/' cost.tf state.tf
   terraform apply -var allow_state_deletion=true
   terraform state rm google_storage_bucket_iam_policy.state
   ```

3. Destroy. This also deletes the state of every repo.

   ```bash
   terraform destroy -var allow_state_deletion=true
   ```

Google keeps a deleted pool's id for 30 days and a deleted role's id for up to 44. To rebuild sooner, pass
`-var pool_id=github-actions-2`, now and every time after. Terraform can bring the roles back within 7 days. The APIs
stay on and the bootstrap project stays, which is free.
