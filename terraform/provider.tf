terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state in S3. Values hardcoded here for this demo; the bucket must
  # already exist. (You can instead leave this `backend "s3" {}` empty and pass
  # values via `terraform init -backend-config=backend.hcl`.)
  backend "s3" {
    bucket  = "vosukula-remote-state"
    key     = "terraform-remote-state-demo"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Demo      = "automated-devops-flow"
    }
  }
}
