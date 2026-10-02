variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for all resource names"
  type        = string
  default     = "autoflow"
}

variable "cluster_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.30"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.50.0.0/16"
}

variable "node_instance_type" {
  description = "Instance type for EKS managed node group (small for a demo)"
  type        = string
  default     = "t3.medium"
}

variable "node_desired_size" {
  description = "Desired node count (keep small for a demo)"
  type        = number
  default     = 2
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 3
}

variable "github_repo" {
  description = "GitHub owner/repo that CI runs from, for the OIDC trust policy."
  type        = string
  default     = "ShivaKrishna44/Automated-Devops-flow-end-to-end"
}

variable "github_subject_claim" {
  description = <<-EOT
    The exact OIDC `sub` claim the GitHub Actions role trusts.

    This repo's owner (ShivaKrishna44) uses GitHub's NEW immutable subject
    claim format, so the real `sub` at runtime will look like:
      repo:ShivaKrishna44@<ownerId>/Automated-Devops-flow-end-to-end@<repoId>:ref:refs/heads/main

    The default below is a WIDE wildcard that works for the first setup so CI's
    OIDC auth succeeds. AFTER the first CI run, tighten it: pull the exact `sub`
    from a CloudTrail AssumeRoleWithWebIdentity event and set it precisely, e.g.
      "repo:ShivaKrishna44@191820242/Automated-Devops-flow-end-to-end@<repoId>:*"
    (the @<ownerId> for ShivaKrishna44 was 191820242 on a sibling repo this
    account — verify, don't assume the repoId).
  EOT
  type    = string
  default = "repo:ShivaKrishna44*/Automated-Devops-flow-end-to-end*:*"
}
