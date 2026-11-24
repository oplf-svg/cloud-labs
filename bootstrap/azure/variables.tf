variable "subscription_id" {
  description = "Azure subscription to bootstrap. Supplied at run time, never committed."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.subscription_id))
    error_message = "subscription_id must be a lower-case GUID."
  }
}

variable "region" {
  description = "Region for every resource."
  type        = string
  default     = "uksouth"
}

variable "plan_extra" {
  description = "Extra read actions for the plan and destroy identities, for example [\"Microsoft.Web/sites/config/list/action\"]."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.plan_extra : can(regex("^Microsoft\\.[A-Za-z.]+/[A-Za-z/]+$", a)) && !strcontains(lower(a), "/write") && !strcontains(lower(a), "/delete")])
    error_message = "plan_extra accepts single actions only, without wildcards, writes or deletes."
  }
}

variable "apply_extra" {
  description = "Names of extra built-in roles for the apply identities, on their own resource group."
  type        = list(string)
  default     = []
}

variable "destroy_extra" {
  description = "Extra actions for the destroy identities, for resource types that Azure cannot remove with a delete action alone."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for a in var.destroy_extra : can(regex("^Microsoft\\.[A-Za-z.]+/[A-Za-z/]+$", a)) && !startswith(lower(a), "microsoft.authorization/")])
    error_message = "destroy_extra accepts single actions only, without wildcards and without Microsoft.Authorization."
  }
}

variable "allow_state_deletion" {
  description = "Set to true only when changing or undoing the bootstrap. Removes the lock that protects it."
  type        = bool
  default     = false
}
