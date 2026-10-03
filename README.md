# Automated DevOps Flow — End to End

A **CrewAI multi-agent system** that takes a demo app from nothing to a running,
monitored deployment on EKS — **from a single command** — with minimal human
interaction. The agents handle infra, CI, GitOps deployment, and monitoring;
a human only approves the few steps that create or destroy billable cloud
resources.

```
python run.py --repo-url https://github.com/<you>/Automated-Devops-flow-end-to-end.git
```

---

## Why there's still *some* human interaction (by design)

"Less human interaction" — yes. "Zero human interaction on steps that spin up a
billable EKS cluster or destroy infrastructure" — deliberately **no**. Those
specific steps (`terraform apply`, `terraform destroy`, installing ArgoCD/
monitoring) are **gated behind a human approval**. Everything else runs
unattended. This mirrors the hard lesson that an agent driving irreversible,
costly cloud operations needs a guardrail, not blind trust.

Agents **orchestrate and observe freely** (read tools); they **cannot** fire a
destructive/costly action without a human having approved it first.

---

## Architecture

```
  python run.py                         (single command)
        │
        ▼
  ORCHESTRATOR  (agents/crew.py — CrewAI; or direct fallback in run.py)
        │   agents call tools via the MCP server, never raw shell
        ▼
  ┌──────────────── MCP SERVER (mcp_server/server.py) ────────────────┐
  │  the SINGLE auditable boundary to the real world                   │
  │                                                                    │
  │  READ (free):   terraform_plan · cluster_health · check_pods ·     │
  │                 get_argocd_app_status · query_prometheus ·         │
  │                 check_targets · get_terraform_output               │
  │                                                                    │
  │  WRITE (gated): terraform_apply · terraform_destroy ·              │
  │                 install_argocd · argocd_sync_app ·                 │
  │                 install_monitoring                                 │
  │                 └─ each calls require_approval() → refuses unless   │
  │                    a human ran `python approve.py <action>`         │
  └────────────────────────────────────────────────────────────────────┘
        │ every call appended to .state/audit.log
        ▼
   AWS (EKS/VPC/ECR/IAM) · GitHub Actions · ArgoCD · Prometheus/Grafana
```

### The phases (what one command does)

| Phase | Does | Gated? |
|-------|------|--------|
| 0. Infra | `terraform plan` → **approve** → `apply` (EKS, VPC, ECR, IAM, OIDC) | ✅ `terraform_apply` |
| 1. Kubectl | `aws eks update-kubeconfig` — points kubectl at the new cluster | — (automatic) |
| 2. ALB | install AWS Load Balancer Controller (wired to its IRSA role) | ✅ `install_alb_controller` |
| 3. CI | GitHub Actions builds image → pushes to ECR → commits new tag | — (runs in GitHub) |
| 4. Deploy | install ArgoCD → apply Application → GitOps sync of the Helm chart | ✅ `install_argocd`, `argocd_sync_app` |
| 5. Monitor | install kube-prometheus-stack (Prometheus + Grafana) | ✅ `install_monitoring` |
| 6. Verify | nodes/pods healthy, ArgoCD synced, Prometheus targets up → PASS/FAIL | — (read only) |

The kubectl config and verify phases are automatic (no approval). Everything
that creates/destroys billable cloud resources is approval-gated.

---

## Repo layout

```
app/                      demo Flask app + Dockerfile (/, /healthz, /metrics)
charts/demo-app/          Helm chart (deployment, service, hpa, configmap)
                          └─ ConfigMap feeds APP_VERSION/LOG_LEVEL/GREETING to
                             the app via envFrom; a checksum annotation rolls
                             the pods when config changes (GitOps config demo)
terraform/                VPC, EKS, ECR, GitHub OIDC role + IRSA
.github/workflows/ci.yml  OIDC build → ECR → GitOps commit
deploy/argocd-application.yaml   ArgoCD App (GitOps source of truth)
mcp_server/
  server.py               MCP tools (read free / write gated) — the boundary
  approval.py             the approval gate (TTL, single-use, audit)
agents/crew.py            CrewAI phase agents
approve.py                HUMAN approval CLI (agents can't call this)
run.py                    single-command entrypoint (+ --teardown)
```

---

## Prerequisites (one-time)

1. **Tools:** `aws` CLI (configured), `terraform` ≥ 1.5, `kubectl`, `helm`,
   Python **3.10–3.13** (not 3.14 — CrewAI constraint).
2. **Terraform state backend** — create the bucket + lock table once:
   ```bash
   aws s3api create-bucket --bucket <your-tf-state-bucket> --region us-east-1
   aws dynamodb create-table --table-name <your-tf-lock-table> \
     --attribute-definitions AttributeName=LockID,AttributeType=S \
     --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST
   cp terraform/backend.hcl.example terraform/backend.hcl   # fill in names
   ```
3. **A GitHub repo** holding this code (ArgoCD + CI point at it). Set
   `var.github_repo` / `var.github_subject_claim` in Terraform so the OIDC
   trust policy matches your repo.
   > GitHub's immutable-subject-claim change: if CI's OIDC auth fails with a
   > generic `AccessDenied`, the real `sub` is
   > `repo:<owner>@<ownerId>/<repo>@<repoId>:ref:refs/heads/main`. Pull the
   > exact value from a CloudTrail `AssumeRoleWithWebIdentity` event and set it.
4. **Python deps:** `pip install -r requirements.txt` (in a 3.10–3.13 venv).

---

## Run it

```bash
# 0. init terraform (once)
cd terraform && terraform init -backend-config=backend.hcl && cd ..

# 1. ONE COMMAND drives the whole flow (infra -> kubectl -> ALB -> CI -> deploy -> monitor -> verify)
python run.py --repo-url https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git

# If infra is ALREADY applied, skip phase 0 and start from kubectl config:
python run.py --repo-url https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git --skip-infra
```

At each gated step the run **pauses** and prints the exact approval command.
In a SECOND terminal, a human approves (single-use, TTL'd):
```bash
python approve.py terraform_apply        --actor <you>   # phase 0 (skip if --skip-infra)
python approve.py install_alb_controller --actor <you>   # phase 2
python approve.py install_argocd         --actor <you>   # phase 4
python approve.py argocd_sync_app        --actor <you>   # phase 4
python approve.py install_monitoring     --actor <you>   # phase 5
```
After each approve, press Enter in the `run.py` terminal to continue.

**Before the deploy phase shows your app, CI must have pushed the image.** Set
the GitHub repo **Actions Variables** (Settings → Secrets and variables →
Actions → Variables) so CI's OIDC auth works, then push to `main` to trigger it:
- `AWS_ROLE_ARN` = `terraform output -raw github_ci_role_arn`
  (e.g. `arn:aws:iam::589389425618:role/autoflow-github-ci`)
- `ECR_REGISTRY` = `terraform output -raw ecr_repository_url` without the
  `/demo-app` suffix (e.g. `589389425618.dkr.ecr.us-east-1.amazonaws.com`)

If the deploy runs before CI has pushed an image, the pods will be in
`ImagePullBackOff` — trigger/finish CI, then let ArgoCD re-sync.

### Reach the app after the flow completes
```bash
kubectl port-forward svc/demo-app 8080:80
curl http://localhost:8080/        # {"service":"demo-app","status":"running",...}
```

---

## Teardown (destroy everything after the demo)

```bash
python run.py --teardown
# in another terminal:
python approve.py terraform_destroy --actor <you>
```

**Then manually check** (Terraform can leave these behind):
- Delete the **ArgoCD app / Helm releases BEFORE destroy** so no orphaned ALBs
  linger (an Ingress-created ALB outlives the cluster otherwise).
- EC2 → **Volumes / Snapshots / AMIs** — delete any left behind.
- The S3 state bucket + DynamoDB lock table persist (reused across runs) —
  delete them separately if you're done entirely.

---

## Safety & honest limitations

- **Local approval is honor-system** (file-based, `--actor` is unauthenticated).
  The real identity enforcement belongs in CI: gate the apply job behind a
  GitHub **Environment with required reviewers**. Documented, not hidden.
- **Approvals are single-use + TTL'd** (`APPROVAL_TTL_MINUTES`, default 30) so a
  stale/forgotten approval can't silently authorize a later run.
- **Every tool call is logged** to `.state/audit.log`.
- **This creates real, billable AWS resources.** Always run `--teardown` after a
  demo, and verify the manual-cleanup items above.
- The agents narrate/orchestrate; correctness of the actual infra changes comes
  from Terraform + the deterministic tool outputs, not from an LLM's summary.
```
