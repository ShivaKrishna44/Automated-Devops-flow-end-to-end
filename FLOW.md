# Code Flow — Automated DevOps Flow (end to end)

How the pieces connect, from `python run.py` down to AWS and into the cluster.
GitHub renders the Mermaid diagram below.

```mermaid
flowchart TD
    USER([You: python run.py --repo-url ...]) --> RUN[run.py<br/>orchestrator entrypoint]

    RUN --> P0[Phase 0: INFRA]
    RUN --> P1[Phase 1: KUBECTL]
    RUN --> P2[Phase 2: ALB]
    RUN --> P3[Phase 3: CI]
    RUN --> P4[Phase 4: DEPLOY]
    RUN --> P5[Phase 5: MONITOR]
    RUN --> P6[Phase 6: VERIFY]

    subgraph GATE[Approval gate - humans only]
      APPROVE[approve.py &lt;action&gt; --actor you]
      STATE[(.state/approvals.json<br/>single-use + TTL)]
      APPROVE --> STATE
    end

    subgraph MCP[mcp_server/server.py - the only path to the real world]
      direction TB
      READ[READ tools: run free<br/>terraform_plan, cluster_health,<br/>get_argocd_app_status, query_prometheus]
      WRITE[WRITE tools: GATED<br/>terraform_apply/destroy, install_alb_controller,<br/>install_argocd, argocd_sync_app, install_monitoring]
      REQ[require_approval checks STATE]
      WRITE --> REQ
      REQ -->|token found| EXEC[run the command]
      REQ -->|no token| BLOCK[BLOCKED]
      AUDIT[(.state/audit.log<br/>every call logged)]
      READ --> AUDIT
      EXEC --> AUDIT
    end

    REQ -.reads.-> STATE

    P0 --> WRITE
    P1 --> READ
    P2 --> WRITE
    P4 --> WRITE
    P5 --> WRITE
    P6 --> READ

    EXEC --> TF[terraform]
    EXEC --> KUBECTL[kubectl]
    EXEC --> HELM[helm]
    EXEC --> AWSCLI[aws cli]

    TF --> AWS[(AWS: VPC, EKS cluster,<br/>node group, ECR, IAM/OIDC)]
    AWSCLI --> AWS
    KUBECTL --> EKS[(EKS cluster)]
    HELM --> EKS

    subgraph CI[GitHub Actions - runs in GitHub, not run.py]
      PUSH[git push to main] --> GHA[ci.yml]
      GHA -->|OIDC assume-role<br/>no static keys| ROLE[autoflow-github-ci role]
      GHA --> BUILD[docker build] --> ECR[(ECR: demo-app image)]
      GHA --> COMMIT[commit new image tag<br/>to charts/demo-app/values.yaml]
    end

    P3 -.waits for.-> CI
    COMMIT --> GIT[(Git repo: Helm chart)]

    subgraph CLUSTER[Inside the EKS cluster]
      ARGO[ArgoCD] -->|watches Git, GitOps sync| APP[demo-app pods]
      APP --> SVC[Service ClusterIP]
      HPA[HPA] -->|reads CPU| METRICS[metrics-server]
      HPA -->|scales| APP
      PROM[Prometheus] -->|scrapes| APP
      GRAF[Grafana] --> PROM
    end

    GIT -.ArgoCD pulls chart.-> ARGO
    ECR -.pods pull image.-> APP
    EKS --- CLUSTER

    USER -.must approve each gated step.-> APPROVE
```

---

## Read it in words

1. **`run.py`** is the single entrypoint. It drives 7 phases in order
   (Infra → Kubectl → ALB → CI → Deploy → Monitor → Verify).

2. **Approval gate (humans only).** A human runs `approve.py <action>`, which
   writes a single-use, TTL'd token to `.state/approvals.json`. Agents cannot
   create approvals.

3. **MCP server = the only path to the real world.** Every phase calls MCP
   tools, never raw shell:
   - **READ** tools (plan/health/status/query) run freely.
   - **WRITE** tools call `require_approval()` → token found = run, no token =
     BLOCKED. Everything is logged to `.state/audit.log`.

4. **Execution layer.** Approved tools shell out to `terraform` / `kubectl` /
   `helm` / `aws`, which act on AWS and the cluster.

5. **CI runs in GitHub (not run.py).** A push triggers `ci.yml` → OIDC
   assume-role (no static keys) → build + push image to ECR → commit the new
   image tag back to the Helm chart in Git. Phase 3 just waits for this.

6. **Inside the cluster.** ArgoCD watches Git and GitOps-syncs the chart →
   `demo-app` pods (pulling the image from ECR) → Service → HPA autoscales
   using metrics-server → Prometheus scrapes, Grafana visualizes.

### The two connections that make GitOps click
- **Git → ArgoCD:** ArgoCD deploys whatever the chart in Git says — and CI
  updated that chart. (the GitOps handoff)
- **ECR → pods:** the image CI pushed is exactly what the pods run.

Full loop: **push code → CI builds & updates Git → ArgoCD deploys from Git →
pods run the ECR image → HPA/Prometheus manage it** — all on infra Terraform
built through the approval-gated MCP tools.
