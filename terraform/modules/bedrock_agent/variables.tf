variable "project_name" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "tags" {
  type = map(string)
}
