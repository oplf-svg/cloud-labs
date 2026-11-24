# Azure runbook

Run once, as Owner of the subscription, in Cloud Shell. Nothing here needs a key, and GitHub plays no part in it.

| You run | It creates | Cost |
|---|---|---|
| `terraform apply`, once | 16 managed identities with one federated credential each, 5 custom roles, 42 role assignments | Free |
| | 1 resource group for the bootstrap, locked against deletion, and 1 empty one per repo | Free |
| | 1 storage account for state, 6 containers: encrypted, versioned, no public access, no keys | Under 0.05 USD a month |

## The short way

Open the Azure portal, start **Cloud Shell** and choose **Bash**. This does every step below. It shows the plan and asks
before it creates anything, and it can be run again if it stops.

```bash
[ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs; git -C ~/cloud-labs pull --ff-only && ~/cloud-labs/bootstrap/scripts/run.sh azure
```

Keep the window open until it has finished: a session without storage forgets its files when closed.

Then follow [Hand it to GitHub](#hand-it-to-github). The rest of this page is for checking, changing and undoing it, or
for doing it by hand.

## Run it by hand

1. Open the Azure portal, start **Cloud Shell** and choose **Bash**. If it asks, choose **No storage account required**.
   Such a session forgets its files when closed, so do steps 6 to 8 without closing it.

2. Get the code. Check that the commit shown is the one you reviewed.

   ```bash
   [ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs
   cd ~/cloud-labs/bootstrap/azure && git pull --ff-only && git log -1 --format='%H %s'
   ```

3. Check the GitHub side. Stop unless all five repos print `ok`.

   ```bash
   python3 ../scripts/github_checks.py environments
   ```

4. Check that this is the right subscription.

   ```bash
   az account show --query '{subscription:name, state:state, user:user.name}' --output table
   ```

5. Get Terraform and set the subscription.

   ```bash
   ../scripts/install-terraform.sh /tmp/tf-bin
   export PATH=/tmp/tf-bin:$PATH TF_DATA_DIR=/tmp/tf-azure TF_VAR_subscription_id=$(az account show --query id --output tsv)
   ```

6. Plan. It must end with `Plan: 95 to add, 0 to change, 0 to destroy.` If Terraform cannot get a token, run `az login`
   and try again.

   ```bash
   terraform init -lockfile=readonly && terraform plan -out=tfplan
   ```

7. Apply, and move the state into the new account straight away. The second command repeats until your new rights on
   the container take effect, which can take some minutes.

   ```bash
   terraform apply tfplan && terraform output -raw backend_tf > backend.tf
   ```

   ```bash
   for i in $(seq 20); do terraform init -lockfile=readonly -migrate-state -force-copy && break; echo "Waiting for access to the container"; sleep 30; done
   ```

   If the apply stops halfway, for example because a new role is not known everywhere yet, keep the shell open, wait a
   minute and repeat from `terraform plan -out=tfplan` in step 6. What exists already is not created twice, so the
   number is smaller.

8. Check that the state is in the account, then remove the local copy. The count must be 96.

   ```bash
   terraform state list | wc -l
   ```

   ```bash
   rm -f terraform.tfstate terraform.tfstate.backup tfplan && terraform plan
   ```

   The plan must say `No changes`.

## Check it

Every subject Azure trusts, against the two lists in this repo:

```bash
diff <(jq -r '.[][]' ../subjects.json ../cost.json | sort) <(for i in $(az identity list -g rg-github-bootstrap --query '[].name' -o tsv); do az identity federated-credential list -g rg-github-bootstrap --identity-name "$i" --query '[].subject' -o tsv; done | sort) && echo "16 subjects match"
```

The storage account: `public` and `keys` are `false`, `tls` is `TLS1_2`, and `versioning` is `true`.

```bash
A=$(terraform output -raw state_bucket); az storage account show -n "$A" --query '{public:allowBlobPublicAccess, keys:allowSharedKeyAccess, tls:minimumTlsVersion, encryption:encryption.keySource}'; az storage account blob-service-properties show -n "$A" -g rg-github-bootstrap --query '{versioning:isVersioningEnabled, softDeleteDays:deleteRetentionPolicy.days}'
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

The identity that reads costs needs nothing else on a pay-as-you-go subscription. If the subscription belongs to a
billing profile (Microsoft Customer Agreement), "Azure charges" has to be on **Yes** in that profile's policies.

## Run it again later

`run.sh` carries out what has changed here since, for example in [subjects.json](../subjects.json). It shows the plan,
asks, and stops if something would be deleted or replaced. Everything that a new subject or a new permission touches
changes in place. Azure takes some minutes to use a changed credential everywhere. It passes no variables and takes back
what one of them had added, so first export every variable you ever set, as in `export TF_VAR_destroy_extra='["..."]'`.

By hand, for example to pass `-var 'destroy_extra=["..."]'`: pass every variable you ever set, each time, because
leaving one out undoes it. Do steps 2 to 5, then:

```bash
A=$(az storage account list -g rg-github-bootstrap --query '[0].name' --output tsv)
printf 'terraform {\n  backend "azurerm" {}\n}\n' > backend.tf
terraform init -lockfile=readonly -backend-config="storage_account_name=$A" -backend-config=container_name=bootstrap -backend-config=key=terraform.tfstate -backend-config=use_azuread_auth=true -backend-config=use_cli=true
terraform plan
```

The lock only blocks deletion. If a change has to replace something, apply once with `-var allow_state_deletion=true`,
then again without it. A federated credential never needs that: change its subject yourself, with the values from
[subjects.json](../subjects.json) in place of `REPO`, `TIER` and `SUBJECT`, and run `run.sh` again.

```bash
az identity federated-credential update -g rg-github-bootstrap --identity-name id-gha-REPO-TIER -n github-actions --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange --subject SUBJECT
```

## Undo it

Destroy every repo's own stacks first. Once these identities are gone, GitHub cannot, and Terraform refuses to delete a
resource group that still has something in it.

1. Do "Run it again later", so that Terraform has the state.

2. Bring the state back to Cloud Shell and remove the lock.

   ```bash
   rm backend.tf && terraform init -lockfile=readonly -migrate-state -force-copy
   sed -i 's/prevent_destroy = true/prevent_destroy = false/' state.tf
   terraform apply -var allow_state_deletion=true
   ```

3. Destroy. This also deletes the state of every repo.

   ```bash
   terraform destroy -var allow_state_deletion=true
   ```
