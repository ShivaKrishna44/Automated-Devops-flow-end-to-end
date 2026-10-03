"""
Automated DevOps Flow — single-command entrypoint.

    python run.py --repo-url https://github.com/<you>/<repo>.git

Runs the FULL lifecycle in order, from one command, pausing only for human
approval before each destructive/costly step:

    0. INFRA     terraform plan -> [APPROVE terraform_apply] -> apply (EKS)
    1. KUBECTL   aws eks update-kubeconfig (automatic, no gate)
    2. ALB       [APPROVE install_alb_controller] -> helm install
    3. CI        reminder/confirm GitHub Actions pushed the image to ECR
    4. DEPLOY    [APPROVE install_argocd] -> install ArgoCD
                 [APPROVE argocd_sync_app] -> apply Application (GitOps)
    5. MONITOR   [APPROVE install_monitoring] -> Prometheus + Grafana
    6. VERIFY    end-to-end health check -> PASS/FAIL

Teardown (also gated):
    python run.py --teardown

Everything except the gated steps runs unattended. The gated steps are the
few that create/destroy billable, hard-to-reverse cloud resources — those
stay human-approved on purpose. Approve each in a SECOND terminal with:
    python approve.py <action> --actor <you>

This entrypoint calls the MCP tool functions directly (works with or without
CrewAI/an LLM installed). With CrewAI configured, agents/crew.py adds the
narrated multi-agent layer on top of these same tools.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))
import server as mcp  # noqa: E402
from approval import status as approval_status  # noqa: E402


def banner(step: str, msg: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {step}: {msg}")
    print("=" * 70)


def need_approval(action: str) -> None:
    print(f"\n[PAUSE] '{action}' is a GATED step (destructive/costly).")
    print(f"   In a SECOND terminal, a human runs:")
    print(f"       python approve.py {action} --actor <your-name>")
    print(f"   Then press Enter here to continue (Ctrl-C to abort).")
    input()


def _check(out: str, phase: str) -> None:
    if out.startswith("BLOCKED") or "ERROR" in out[:300] or "Error" in out[:300]:
        print(out)
        raise SystemExit(f"[{phase}] did not succeed - fix/approve and re-run.")
    print(out)


def phase_infra() -> None:
    banner("PHASE 0 - INFRA", "terraform plan, then human-approved apply")
    print(mcp.terraform_plan())
    need_approval("terraform_apply")
    _check(mcp.terraform_apply(), "INFRA")


def phase_kubectl() -> None:
    banner("PHASE 1 - KUBECTL", "point kubectl at the new cluster (automatic)")
    _check(mcp.configure_kubectl(), "KUBECTL")


def phase_alb() -> None:
    banner("PHASE 2 - ALB CONTROLLER", "install AWS Load Balancer Controller")
    need_approval("install_alb_controller")
    _check(mcp.install_alb_controller(), "ALB")


def phase_ci() -> None:
    banner("PHASE 3 - CI", "GitHub Actions builds & pushes demo-app to ECR")
    repo = mcp.get_terraform_output("ecr_repository_url")
    print(f"ECR repo: {repo}")
    print("GitHub Actions (ci.yml) builds on push to main and commits the new")
    print("image tag into charts/demo-app/values.yaml. Make sure the repo's")
    print("Actions Variables are set: AWS_ROLE_ARN, ECR_REGISTRY.")
    print("Press Enter once the CI run has succeeded (image in ECR).")
    input()


def phase_deploy(repo_url: str) -> None:
    banner("PHASE 4 - DEPLOY", "install ArgoCD + apply Application (GitOps)")
    need_approval("install_argocd")
    _check(mcp.install_argocd(), "ARGOCD-INSTALL")
    print("Waiting for ArgoCD server to come up...")
    time.sleep(40)
    need_approval("argocd_sync_app")
    _check(mcp.argocd_sync_app(repo_url=repo_url), "ARGOCD-SYNC")


def phase_monitoring() -> None:
    banner("PHASE 5 - MONITORING", "install Prometheus + Grafana")
    need_approval("install_monitoring")
    _check(mcp.install_monitoring(), "MONITORING")


def phase_verify() -> None:
    banner("PHASE 6 - VERIFY", "end-to-end health check")
    print(mcp.cluster_health())
    print("\nArgoCD app status:", mcp.get_argocd_app_status())
    print("Prometheus targets down:", mcp.check_targets())
    print("\n Flow complete. Reach the app:")
    print("   kubectl port-forward svc/demo-app 8080:80")
    print("   curl http://localhost:8080/")


def teardown() -> None:
    banner("TEARDOWN", "destroy ALL demo infra (gated)")
    print("Destroys EKS, VPC, ECR, IAM. Delete ArgoCD app / Helm releases FIRST")
    print("so no orphaned ALBs linger.")
    need_approval("terraform_destroy")
    print(mcp.terraform_destroy())
    print("\n  Manual cleanup check:")
    print("   - EC2 Volumes / Snapshots / AMIs left behind")
    print("   - any LoadBalancers from Services/Ingress")
    print("   - the EKS CloudWatch log group + KMS alias (AWS keeps these):")
    print("       aws logs delete-log-group --log-group-name /aws/eks/<cluster>/cluster --region <r>")
    print("       aws kms delete-alias --alias-name alias/eks/<cluster> --region <r>")


def main() -> int:
    p = argparse.ArgumentParser(description="Automated DevOps Flow — one command.")
    p.add_argument("--repo-url", help="Git repo URL ArgoCD deploys from")
    p.add_argument("--teardown", action="store_true")
    p.add_argument("--skip-infra", action="store_true",
                   help="infra already applied; start from kubectl config")
    p.add_argument("--skip-ci-wait", action="store_true",
                   help="don't pause for CI (image already in ECR)")
    args = p.parse_args()

    if args.teardown:
        teardown()
        return 0

    if not args.repo_url:
        print("ERROR: --repo-url is required (the repo ArgoCD deploys from).")
        return 1

    print("Approvals on record:", approval_status() or "(none)")

    if not args.skip_infra:
        phase_infra()
    phase_kubectl()
    phase_alb()
    if not args.skip_ci_wait:
        phase_ci()
    phase_deploy(args.repo_url)
    phase_monitoring()
    phase_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
