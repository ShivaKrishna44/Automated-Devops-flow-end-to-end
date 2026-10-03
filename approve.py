"""
Human approval CLI — the ONLY way a destructive/costly action gets authorized.

A human runs this; agents cannot. Example:
    python approve.py terraform_apply --actor alice
    python approve.py terraform_destroy --actor alice

It prints what the action does and requires you to type the action name back
to confirm (prevents an accidental one-word approval of the wrong thing).
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))
from approval import grant, status  # noqa: E402

ACTIONS = {
    "terraform_apply": "Provision EKS + VPC + ECR + IAM. Creates BILLABLE AWS resources.",
    "terraform_destroy": "DESTROY all demo infra. Irreversible.",
    "install_alb_controller": "Install the AWS Load Balancer Controller (Helm) into the cluster.",
    "install_argocd": "Install ArgoCD into the cluster.",
    "argocd_sync_app": "Create the ArgoCD Application and start deploying the app.",
    "install_monitoring": "Install Prometheus + Grafana (kube-prometheus-stack).",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", nargs="?", choices=list(ACTIONS) + ["status"])
    p.add_argument("--actor", help="Your name/identity (for the audit trail)")
    p.add_argument("--yes", action="store_true", help="skip the typed confirmation (not recommended)")
    args = p.parse_args()

    if not args.action or args.action == "status":
        print("Current approvals:")
        for k, v in (status() or {}).items():
            print(f"  {k}: actor={v['actor']} used={v['used']}")
        print("\nUsage: python approve.py <action> --actor <name>")
        print("Actions:")
        for a, desc in ACTIONS.items():
            print(f"  {a:20} {desc}")
        return 0

    if not args.actor:
        print("ERROR: --actor is required (who is approving this?)")
        return 1

    print(f"\nAction:  {args.action}")
    print(f"Effect:  {ACTIONS[args.action]}")
    print(f"Actor:   {args.actor}\n")

    if not args.yes:
        typed = input(f"Type the action name '{args.action}' to confirm: ").strip()
        if typed != args.action:
            print("Confirmation did not match. Aborted. Nothing approved.")
            return 1

    grant(args.action, args.actor)
    print(f"Approved '{args.action}' as {args.actor}. Valid for a limited time, single-use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
