# Runbook 3 — AUTOMATED (one command): Infra → CI/CD → Deploy → ArgoCD → Monitoring

The **code / automated** version. Instead of clicking (RUNBOOK-1) or running
commands one by one (RUNBOOK-2), a single command drives the whole chain, with
CrewAI agents orchestrating and an MCP server executing the real actions. The
only human touchpoints are **approval gates** before each
destructive/costly step.

Account `589389425618` · Region `us-east-1` · Repo
`ShivaKrishna44/Automated-Devops-flow-end-to-end`

```
python run.py --repo-url https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git
```

---

## How the six items map to the automated flow

| Your item | Automated step (phase in run.py) | Gated? |
|-----------|----------------------------------|--------|
| **infra** | Phase 0 — `terraform plan` → approve → `apply` (VPC + IAM + ECR + OIDC) | ✅ `terraform_apply` |
| **cluster** | part of Phase 0 — the EKS cluster + node group are in the same Terraform | ✅ (same apply) |
| **CICD** | Phase 3 — GitHub Actions (`ci.yml`) builds → pushes ECR → commits Helm tag | — (runs in GitHub) |
| **k8s app deploy** | Phase 4 — ArgoCD GitOps-syncs `charts/demo-app` to the cluster | ✅ `argocd_sync_app` |
| **argocd** | Phase 4 — `install_argocd` installs ArgoCD into the cluster | ✅ `install_argocd` |
| **monitor** | Phase 5 — `install_monitoring` (kube-prometheus-stack) | ✅ `install_monitoring` |
| (connect) | Phase 1 — `aws eks update-kubeconfig` runs automatically | — |
| (alb) | Phase 2 — `install_alb_controller` wired to its IRSA role | ✅ `install_alb_controller` |
| (verify) | Phase 6 — health check: nodes, ArgoCD app, Prometheus targets | — |

---

## Why there are still approval gates (the design)

This is the "less human interaction" version — but the steps that create or
destroy **billable, hard-to-reverse** cloud resources (terraform apply/destroy,
installing cluster-wide controllers) are gated behind a human approval. Agents
orchestrate and observe freely; they **cannot** fire a gated action unless a
human approved it. That's deliberate — an agent shouldn't blind-apply an EKS
cluster or tear one down. Everything else runs unattended.

---

## Prerequisites (one-time)

1. Tools on your machine: `aws` (configured), `terraform` ≥ 1.5, `kubectl`,
   `helm`, Python **3.10–3.13** (not 3.14 — CrewAI constraint).
2. Terraform S3 state backend exists (bucket + the backend block in
   `terraform/provider.tf` is already set).
3. Python deps: `pip install -r requirements.txt`.
4. GitHub repo pushed, and its **Actions Variables** set so CI can run:
   - `AWS_ROLE_ARN`  = `terraform output -raw github_ci_role_arn`
   - `ECR_REGISTRY`  = `589389425618.dkr.ecr.us-east-1.amazonaws.com`

---

## Run it — the single command

```bash
cd Automated-Devops-flow-end-to-end

# full flow from scratch (includes infra):
python run.py --repo-url https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git

# if infra is ALREADY applied, skip phase 0:
python run.py --repo-url https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git --skip-infra
```

The run **pauses** at each gated step and prints the exact approval command.
In a SECOND terminal, a human approves (single-use, TTL'd):

```bash
python approve.py terraform_apply        --actor shiva   # infra + cluster
python approve.py install_alb_controller --actor shiva   # ALB controller
python approve.py install_argocd         --actor shiva   # ArgoCD
python approve.py argocd_sync_app         --actor shiva   # deploy the app
python approve.py install_monitoring     --actor shiva   # Prometheus+Grafana
```
After each approve, press **Enter** in the `run.py` terminal to continue.

Between phase 2 and phase 4 the run pauses for **CI** — make sure the GitHub
Actions run has built & pushed the image (phase 3) before letting ArgoCD
deploy, or the pods land in `ImagePullBackOff`.

---

## What each phase does under the hood

- **Phase 0 Infra+Cluster** — the agent runs `terraform plan` (via the MCP
  `terraform_plan` read tool), prints it, waits for `terraform_apply` approval,
  then runs `terraform apply`. Builds VPC, EKS cluster, node group, ECR, IAM/
  OIDC in one shot.
- **Phase 1 Connect** — MCP `configure_kubectl` runs `aws eks
  update-kubeconfig` automatically (no gate — it only edits local kubeconfig).
- **Phase 2 ALB** — MCP `install_alb_controller` helm-installs the AWS Load
  Balancer Controller, pulling its IRSA role ARN from terraform output.
- **Phase 3 CICD** — reminds you GitHub Actions builds/pushes the image; you
  confirm the ECR image exists.
- **Phase 4 Deploy+ArgoCD** — `install_argocd` installs ArgoCD, then
  `argocd_sync_app` applies the Application (your repo URL auto-substituted) so
  ArgoCD GitOps-syncs `charts/demo-app`.
- **Phase 5 Monitor** — `install_monitoring` helm-installs
  kube-prometheus-stack (Prometheus + Grafana).
- **Phase 6 Verify** — reads cluster health, ArgoCD app status, Prometheus
  targets; prints how to reach the app.

Every tool call is logged to `.state/audit.log`. Approvals live in
`.state/approvals.json` (single-use, expire after `APPROVAL_TTL_MINUTES`).

---

## The CrewAI + MCP layer (what "automated" means here)

```
python run.py
    │
    ▼
Orchestrator (agents/crew.py — CrewAI agents, or run.py's direct path)
    │  agents call tools through the MCP server (never raw shell)
    ▼
MCP server (mcp_server/server.py) — the single auditable boundary
    │  READ tools: free     WRITE tools: require an approval token
    ▼
Terraform / aws / kubectl / helm  →  AWS, EKS, ArgoCD, Prometheus
```
- Read tools (plan, status, health, query) run freely.
- Write tools (apply/destroy, install_*, sync) call `require_approval()` and
  refuse unless a human ran `approve.py` for that exact action.

---

## Teardown (automated, also gated)

```bash
python run.py --teardown
# second terminal:
python approve.py terraform_destroy --actor shiva
```
Then the manual cleanup the run reminds you about (AWS keeps these after a
cluster delete):
```bash
aws logs delete-log-group --log-group-name /aws/eks/autoflow-cluster/cluster --region us-east-1
aws kms delete-alias --alias-name alias/eks/autoflow-cluster --region us-east-1
```
Delete the ArgoCD app + any LoadBalancer BEFORE destroy, or an orphaned ALB
keeps billing you.

---

## Honest limitations (same as the project README)

- **Local approval is honor-system** (`--actor` isn't authenticated). Real
  identity enforcement belongs in CI (gate the apply job behind a GitHub
  Environment with required reviewers).
- **CrewAI needs Python 3.10–3.13.** `run.py` has a non-LLM direct-orchestration
  fallback so the flow still runs without CrewAI installed — but the narrated
  multi-agent experience needs it + an LLM key.
- **This creates real, billable AWS resources.** Always `--teardown` after.
- Correctness of infra changes comes from Terraform + deterministic tool
  outputs, not from an LLM's summary.

---

## The three runbooks (pick your style)

| Runbook | Style | File |
|---------|-------|------|
| 1 | Console, click-by-click | `RUNBOOK-1-CONSOLE.md` |
| 2 | CLI, command-by-command | `RUNBOOK-2-CLI.md` |
| 3 | Automated, one command (this file) | `RUNBOOK-3-AUTOMATED.md` |

Same six-item chain — infra + cluster + CI/CD + k8s app deploy + ArgoCD +
monitoring — three ways to do it.
