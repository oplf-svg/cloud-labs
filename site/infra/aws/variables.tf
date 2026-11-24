variable "account_id" {
  type        = string
  description = "The account to deploy into."

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "An AWS account id has 12 digits."
  }
}

variable "addresses" {
  type        = set(string)
  description = "Every address of the site, such as / or /proof/ or /favicon.svg. Nothing else reaches the storage."

  validation {
    condition     = contains(var.addresses, "/") && alltrue([for a in var.addresses : can(regex("^/(?:[A-Za-z0-9_][A-Za-z0-9._-]*/)*(?:[A-Za-z0-9_][A-Za-z0-9._-]*)?$", a))])
    error_message = "An address is / or one or more plain names after it, and / has to be one of them."
  }
}

variable "on_free_plan" {
  type        = bool
  description = "Whether the distribution is on CloudFront's free plan, which has no overage charges. It is switched off until then."
}
