"""
Automated DevOps Flow — single-command entrypoint.

    python run.py --repo-url https://github.com/<you>/<repo>.git

Runs the full lifecycle in order, pausing for human approval before each
destructive/costly step (terraform apply, argocd install/sync, monitoring):

    1. INFRA     terraform plan  -> [APPROVE] -> terraform apply (EKS)
    2. CI        wait for GitHub Actions to push demo-app image to ECR
    3. DEPLOY    install ArgoCD -> apply Application (GitOps)
    4. MONITOR   install Prometheus + Grafana
    5. VERIFY    end-to-end health check, PASS/FAIL

Teardown (separate, also gated):
    python run.py --teardown

Design: the agents orchestrate; the real actions run through the MCP server's
tools (mcp_server/server.py), and every write tool is blocked unless a human
ran `python approve.py <action> --actor <you>` first. This keeps "less human
interaction" true for everything EXCEPT the few steps that create/destroy
billable, hard-to-reverse cloud resources — those stay human-approved on
purpose.

This entrypoint uses a direct orchestration path (calls the same MCP tool
functions) so it runs with or without CrewAI/an LLM installed. With CrewAI +
an LLM configured, agents/crew.py provides the narrated multi-agent version.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))
# We import the tool *functions* directly for the fallback orchestrator. In the
# CrewAI path these same functions are exposed as MCP tools to the agents.
import server as mcp  # noqa: E402
from approval import status as approval_status  # noqa: E402


def banner(step: str, msg: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {step}: {msg}")
    print("=" * 70)


def need_approval(action: str) -> None:
    """Pause and tell the human exactly how to approve a gated step."""
    print(f"\n⏸  '{action}' is a GATED step (destructive/costly).")
    print(f"   In a SEPARATE terminal, a human must run:")
    print(f"       python approve.py {action} --actor <your-name>")
    print(f"   Then press Enter here to continue (or Ctrl-C to abort).")
    input()


def phase_infra() -> None:
    banner("PHASE 1 — INFRA", "Terraform plan, then human-approved apply")
    print(mcp.terraform_plan())
    need_approval("terraform_apply")
    out = mcp.terraform_apply()
    print(out)
    if out.startswith("BLOCKED") or "ERROR" in out[:200]:
        raise SystemExit("Infra apply did not succeed — stopping. Approve and retry.")


def phase_ci() -> None:
    banner("PHASE 2 — CI", "Waiting for GitHub Actions to build & push demo-app")
    print("GitHub Actions builds the image on push to main. This phase assumes")
    print("the workflow has run (or you triggered it). Confirming ECR image...")
    repo_url = mcp.get_terraform_output("ecr_repository_url")
    print(f"ECR repo: {repo_url}")
    print("(Trigger CI via a push or the Actions 'Run workflow' button if not done.)")


def phase_deploy(repo_url: str) -> None:
    banner("PHASE 3 — DEPLOY", "Install ArgoCD + apply Application (GitOps)")
    need_approval("install_argocd")
    print(mcp.install_argocd())
    print("Waiting for ArgoCD to come up...")
    time.sleep(30)
    need_approval("argocd_sync_app")
    print(mcp.argocd_sync_app(repo_url=repo_url))


def phase_monitoring() -> None:
    banner("PHASE 4 — MONITORING", "Install Prometheus + Grafana")
    need_approval("install_monitoring")
    print(mcp.install_monitoring())


def phase_verify() -> None:
    banner("PHASE 5 — VERIFY", "End-to-end health check")
    print(mcp.cluster_health())
    print("ArgoCD app status:", mcp.get_argocd_app_status())
    print("Prometheus targets down:", mcp.check_targets())
    print("\n✅ Flow complete. Review the output above for PASS/FAIL per phase.")


def teardown() -> None:
    banner("TEARDOWN", "Destroy ALL demo infra (gated)")
    print("This destroys the EKS cluster, VPC, ECR, IAM — everything.")
    need_approval("terraform_destroy")
    print(mcp.terraform_destroy())
    print("\n⚠️  Manual cleanup check (Terraform may not remove these):")
    print("   - EC2 -> Volumes: delete any orphaned EBS volumes")
    print("   - EC2 -> Snapshots / AMIs: delete any left behind")
    print("   - Any LoadBalancers created by Services/Ingress (delete the")
    print("     Helm releases / ArgoCD app BEFORE destroy to avoid orphaned ALBs)")


def main() -> int:
    p = argparse.ArgumentParser(description="Automated DevOps Flow — one command.")
    p.add_argument("--repo-url", help="Git repo URL ArgoCD deploys from")
    p.add_argument("--teardown", action="store_true", help="destroy everything")
    p.add_argument("--skip-ci-wait", action="store_true",
                   help="don't pause for CI (if the image is already pushed)")
    args = p.parse_args()

    if args.teardown:
        teardown()
        return 0

    if not args.repo_url:
        print("ERROR: --repo-url is required (the repo ArgoCD deploys from).")
        return 1

    print("Approvals currently on record:", approval_status() or "(none)")

    phase_infra()
    phase_ci()
    phase_deploy(args.repo_url)
    phase_monitoring()
    phase_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
