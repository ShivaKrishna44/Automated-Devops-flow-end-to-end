output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value     = module.eks.cluster_endpoint
  sensitive = true
}

output "ecr_repository_url" {
  description = "Push the demo-app image here"
  value       = aws_ecr_repository.demo_app.repository_url
}

output "github_ci_role_arn" {
  description = "Set this as AWS_ROLE_ARN in the GitHub repo for CI OIDC auth"
  value       = aws_iam_role.github_ci.arn
}

output "alb_controller_role_arn" {
  description = "IRSA role ARN for the AWS Load Balancer Controller"
  value       = module.alb_controller_irsa.iam_role_arn
}

output "region" {
  value = var.aws_region
}
