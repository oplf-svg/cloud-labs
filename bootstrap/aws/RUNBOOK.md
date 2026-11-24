# AWS runbook

Run once, as an administrator, in CloudShell. Nothing here needs a key, and GitHub plays no part in it.

| You run | It creates | Cost |
|---|---|---|
| `terraform apply`, once | 1 OIDC provider, 15 roles, 5 policies and their attachments | Free |
| | 1 S3 bucket for state: encrypted, versioned, public access blocked | Under 0.05 USD a month |

## Run it

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

## Run it again later

For example to pass `-var 'destroy_extra=["..."]'`. Pass every variable you ever set, each time: leaving one out undoes
it. Do steps 2 to 4, then:

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
