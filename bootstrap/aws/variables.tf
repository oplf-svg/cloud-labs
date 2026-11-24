variable "account_id" {
  description = "AWS account to bootstrap. Supplied at run time, never committed. Terraform stops if you are signed in to a different account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be 12 digits."
  }
}

variable "region" {
  description = "Region for the state bucket. IAM is global."
  type        = string
  default     = "eu-west-2"
}

variable "plan_extra" {
  description = "Extra read actions for the plan and destroy roles, for example [\"redshift:DescribeClusters\"]."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.plan_extra : can(regex("^[a-z0-9-]+:(BatchGet|Describe|Get|List)[A-Za-z]+$", a))])
    error_message = "plan_extra accepts single read actions only, without wildcards."
  }
}

variable "apply_extra" {
  description = "ARNs of extra managed policies for the apply roles."
  type        = list(string)
  default     = []
}

variable "destroy_extra" {
  description = "Extra actions for the destroy roles, for resource types that AWS cannot remove with a delete action alone."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.destroy_extra : can(regex("^[a-z0-9-]+:[A-Z][A-Za-z]+$", a)) && !startswith(a, "iam:")])
    error_message = "destroy_extra accepts single actions only, without wildcards and without iam."
  }
}

variable "allow_state_deletion" {
  description = "Set to true only when undoing the bootstrap. Lets Terraform empty the state bucket."
  type        = bool
  default     = false
}
