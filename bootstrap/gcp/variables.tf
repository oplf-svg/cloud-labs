variable "project_id" {
  description = "Project that the repos deploy into. Supplied at run time, never committed."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a project id, not a name or a number."
  }
}

# Several of Google's own service agents can read every bucket in their project, and some of them
# run code for whoever asks. A bucket cannot refuse them, so state lives where they do not exist.
variable "bootstrap_project_id" {
  description = "A second project that holds only the trust and the state. Supplied at run time, never committed."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.bootstrap_project_id))
    error_message = "bootstrap_project_id must be a project id, not a name or a number."
  }

  validation {
    condition     = var.bootstrap_project_id != var.project_id
    error_message = "The trust and the state need a project of their own, different from project_id."
  }
}

variable "region" {
  description = "Region for the state bucket. IAM is global."
  type        = string
  default     = "europe-west2"
}

variable "pool_id" {
  description = "Workload identity pool id. A deleted pool keeps its id for 30 days, so pass a new one if you rebuild within that time."
  type        = string
  default     = "github-actions"
}

variable "plan_extra" {
  description = "Extra read permissions for the plan and destroy identities, for example [\"spanner.instances.get\"]."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for p in var.plan_extra : can(regex("^[a-z]+\\.[A-Za-z]+\\.(get|list)[A-Za-z]*$", p))])
    error_message = "plan_extra accepts single get or list permissions only."
  }
}

variable "apply_extra" {
  description = "Extra predefined roles for the apply identities."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for r in var.apply_extra : startswith(r, "roles/") && !contains(["roles/owner", "roles/editor", "roles/admin", "roles/writer"], r)])
    error_message = "apply_extra accepts predefined roles, but not the basic roles."
  }
}

variable "destroy_extra" {
  description = "Extra permissions for the destroy identities, for resource types that Google Cloud cannot remove with a delete permission alone."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for p in var.destroy_extra : can(regex("^[a-z]+\\.[A-Za-z]+\\.[A-Za-z]+$", p)) && !can(regex("(?i)(setIamPolicy|actAs|getAccessToken|create)", p))])
    error_message = "destroy_extra accepts single permissions, without creating, impersonating or changing access."
  }
}

variable "allow_state_deletion" {
  description = "Set to true only when undoing the bootstrap. Lets Terraform empty the state bucket."
  type        = bool
  default     = false
}
