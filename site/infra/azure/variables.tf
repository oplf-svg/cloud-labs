variable "subscription_id" {
  type        = string
  description = "The subscription to deploy into."

  validation {
    condition     = can(regex("^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", var.subscription_id))
    error_message = "A subscription id is a GUID."
  }
}
