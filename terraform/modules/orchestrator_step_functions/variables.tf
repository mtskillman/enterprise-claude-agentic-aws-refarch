variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "agent_lambda_arn" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "tags" {
  type = map(string)
}
