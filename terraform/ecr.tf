# ECR repo for the demo app image. force_delete = true so `terraform destroy`
# removes it even if images are present (important for clean demo teardown).
resource "aws_ecr_repository" "demo_app" {
  name                 = "demo-app"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
