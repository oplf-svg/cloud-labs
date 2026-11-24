# AWS runbook

Run once, as an administrator, in CloudShell. Nothing here needs a key, and GitHub plays no part in it.

| You run | It creates | Cost |
|---|---|---|
| `terraform apply`, once | 1 OIDC provider, 15 roles, 5 policies and their attachments | Free |
| | 1 S3 bucket for state: encrypted, versioned, public access blocked | Under 0.05 USD a month |

## Which account

The account must be allowed to create identity providers and to use Europe (London). One made with
[Sign up for AWS (new)](https://docs.aws.amazon.com/accounts/latest/reference/sign-up-for-aws.html) is allowed neither,
on its Free or its Paid plan: [AWS's own policies](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html)
deny `iam:*Provider*` in it and keep it in the region AWS chose. CloudShell then says that London is unavailable. There
are two ways on:

- Use an account made with **Sign up for AWS (advanced)**.
- Upgrade the account to the Paid plan and [activate advanced features](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html).
  Neither can be undone, and activating removes any spend limit. Then:
  1. In the management account, open **AWS Organizations**, **Policies**, **Service control policies** and add
     `eu-west-2` to the regions in the statement `RegionFloor` of `AdvancedModeRegionRestrictionSecurityControlPolicy`.
  2. In the project's account, open the console's **Unified Settings**, **Account settings** and add London to
     **Visible Regions**. Until then the console says that access to the region has been restricted.
  3. Run the rest of this page in the project's account. Keep the management account for administration.

`run.sh` checks for both limits before it plans anything.

## The short way

Open the AWS console, switch the region to **Europe (London)** and open **CloudShell**. This does every step below. It
shows the plan and asks before it creates anything, and it can be run again if it stops.

```bash
[ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs; git -C ~/cloud-labs pull --ff-only && ~/cloud-labs/bootstrap/scripts/run.sh aws
```

Then follow [Hand it to GitHub](#hand-it-to-github). The rest of this page is for checking, changing and undoing it, or
for doing it by hand.

## Run it by hand

1. Open the AWS console, switch the region to **Europe (London)** and open **CloudShell**.

2. Get the code. Check that the commit shown is the one you reviewed.

   ```bash
   [ -d ~/cloud-labs ] || git clone https://github.com/oplf-svg/cloud-labs.git ~/cloud-labs
   cd ~/cloud-labs/bootstrap/aws && git pull --ff-only && git log -1 --format='%H %s'
   ```

3. Check the GitHub side. Stop unless all five repos print `ok`.

   ```bash
   python3 ../scripts/github_checks.py environments
   ```

4. Get Terraform and set the account. The provider is too big for CloudShell's home folder, so it goes in `/tmp`.

   ```bash
   ../scripts/install-terraform.sh /tmp/tf-bin
   export PATH=/tmp/tf-bin:$PATH TF_DATA_DIR=/tmp/tf-aws TF_VAR_account_id=$(aws sts get-caller-identity --query Account --output text)
   ```

5. Check that the account does not trust GitHub yet. If this prints a line, stop: the provider has to be imported first.
   If it is denied, see [Which account](#which-account).

   ```bash
   aws iam list-open-id-connect-providers --output text | grep token.actions.githubusercontent.com
   ```

6. Plan. It must end with `Plan: 104 to add, 0 to change, 0 to destroy.`

   ```bash
   terraform init -lockfile=readonly && terraform plan -out=tfplan
   ```

7. Apply, and move the state into the new bucket straight away.

   ```bash
   terraform apply tfplan && terraform output -raw backend_tf > backend.tf && terraform init -lockfile=readonly -migrate-state -force-copy
   ```

   If the apply stops halfway, keep the shell open, fix the cause and repeat from `terraform plan -out=tfplan` in step
   6. What exists already is not created twice, so the number is smaller.

8. Check that the state is in the bucket, then remove the local copy. The count must be 104.

   ```bash
   terraform state list | wc -l
   ```

   ```bash
   rm -f terraform.tfstate terraform.tfstate.backup tfplan && terraform plan
   ```

   The plan must say `No changes`.

## Check it

Every subject that any role in the account trusts, against the list in this repo:

```bash
diff <(jq -r '.[][]' ../subjects.json | sort) <(aws iam list-roles --output json | jq -r '.Roles[].AssumeRolePolicyDocument.Statement | if type == "array" then .[] else . end | select(tostring | contains("token.actions.githubusercontent.com")) | .Condition.StringEquals["token.actions.githubusercontent.com:sub"] // "a role without one exact subject"' | sort) && echo "15 subjects match"
```

The bucket: four times `true`, `Enabled`, and `AES256`.

```bash
B=$(terraform output -raw state_bucket); aws s3api get-public-access-block --bucket "$B"; aws s3api get-bucket-versioning --bucket "$B"; aws s3api get-bucket-encryption --bucket "$B"
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

## Run it again later

`run.sh` carries out what has changed here since, for example in [subjects.json](../subjects.json). It shows the plan,
asks, and stops if something would be deleted or replaced. Everything that a new subject or a new permission touches
changes in place. It passes no variables and takes back what one of them had added, so first export every variable you
ever set, as in `export TF_VAR_destroy_extra='["..."]'`.

By hand, for example to pass `-var 'destroy_extra=["..."]'`: pass every variable you ever set, each time, because
leaving one out undoes it. Do steps 2 to 4, then:

```bash
B=$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'tfstate-')].Name | [0]" --output text)
printf 'terraform {\n  backend "s3" {}\n}\n' > backend.tf
terraform init -lockfile=readonly -backend-config="bucket=$B" -backend-config=key=bootstrap/terraform.tfstate -backend-config=region=eu-west-2 -backend-config=encrypt=true -backend-config=use_lockfile=true
terraform plan
```

## Undo it

Destroy every repo's own stacks first. Once these roles are gone, GitHub cannot.

1. Do "Run it again later", so that Terraform has the state.

2. Bring the state back to CloudShell and allow the bucket to be deleted.

   ```bash
   rm backend.tf && terraform init -lockfile=readonly -migrate-state -force-copy
   sed -i 's/prevent_destroy = true/prevent_destroy = false/' state.tf
   terraform apply -var allow_state_deletion=true
   ```

3. Destroy. This also deletes the state of every repo.

   ```bash
   terraform destroy -var allow_state_deletion=true
   ```
