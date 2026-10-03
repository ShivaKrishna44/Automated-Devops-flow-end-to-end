# ============================================================================
# IRSA HANDS-ON LAB — a pod assumes an IAM role via the cluster's OIDC provider
# ============================================================================
# Separate mini Terraform config (own local state) reusing the running
# autoflow-cluster. It looks up the cluster's OIDC provider automatically.
#
# What it builds:
#   1. An S3 bucket (what the pod will be allowed to read).
#   2. An IAM policy granting read on ONLY that bucket.
#   3. An IAM role whose TRUST POLICY says "only a token whose `sub` is exactly
#      system:serviceaccount:<ns>:<sa> may assume me" — the heart of IRSA.
#   (ServiceAccount + test pod are applied with kubectl in IRSA-LAB.md.)
#
# This trust policy is the SAME shape as ../terraform/github-oidc.tf (GitHub
# Actions OIDC): federated principal + AssumeRoleWithWebIdentity + sub/aud
# conditions. Only the issuer and the `sub` format differ.
# ============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # local state — throwaway lab
}

provider "aws" {
  region = var.region
}

variable "region" {
  default = "us-east-1"
}
variable "cluster_name" {
  default = "autoflow-cluster"
}
variable "namespace" {
  default = "default"
}
variable "service_account_name" {
  default = "irsa-demo-sa"
}

data "aws_caller_identity" "current" {}

# Look up the EXISTING cluster + its OIDC issuer (don't create anything).
data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

locals {
  oidc_url = replace(data.aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")
  oidc_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.oidc_url}"
}

# 1. The bucket the pod will read.
resource "aws_s3_bucket" "demo" {
  bucket        = "irsa-lab-${data.aws_caller_identity.current.account_id}-demo"
  force_destroy = true
}

resource "aws_s3_object" "hello" {
  bucket  = aws_s3_bucket.demo.id
  key     = "hello.txt"
  content = "If you can read this from inside the pod, IRSA works."
}

# 2. IAM policy: read ONLY this bucket.
data "aws_iam_policy_document" "s3_read" {
  statement {
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.demo.arn, "${aws_s3_bucket.demo.arn}/*"]
  }
}

resource "aws_iam_policy" "s3_read" {
  name   = "irsa-lab-s3-read"
  policy = data.aws_iam_policy_document.s3_read.json
}

# 3. THE KEY PART — IRSA role + OIDC trust policy scoped to ONE ServiceAccount.
data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn] # trust THIS cluster's OIDC provider
    }

    # Only tokens for exactly this ServiceAccount may assume the role.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account_name}"]
    }

    # Audience must be sts.amazonaws.com (standard for IRSA).
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "irsa_demo" {
  name               = "irsa-lab-demo-role"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.irsa_demo.name
  policy_arn = aws_iam_policy.s3_read.arn
}

output "role_arn" {
  value = aws_iam_role.irsa_demo.arn
}
output "bucket_name" {
  value = aws_s3_bucket.demo.id
}
output "oidc_provider_url" {
  value = local.oidc_url
}
output "sa_annotation" {
  description = "Put this annotation on the ServiceAccount"
  value       = "eks.amazonaws.com/role-arn: ${aws_iam_role.irsa_demo.arn}"
}
