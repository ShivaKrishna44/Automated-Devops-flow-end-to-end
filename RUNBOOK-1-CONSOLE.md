# Runbook 1 — CONSOLE (click-by-click): Infra → CI/CD → Deploy → Monitoring

Everything done through web consoles (AWS Console, GitHub, ArgoCD UI, Grafana),
step by step. This is the **Console-only** version. The matching CLI version is
`RUNBOOK-2-CLI.md`.

Assumes you work from an **EC2 management instance** that has an IAM role
attached (so no access keys). Account `589389425618`, Region `us-east-1`.

---

## STAGE 0 — Management EC2 instance + its IAM role

### Step 0.1 — Create the IAM role for the EC2
1. Open the AWS Console, search **IAM**.
2. Left menu → **Roles** → **Create role**.
3. **Trusted entity type** → **AWS service**.
4. **Service or use case** → **EC2** → **Next**.
5. On **Add permissions**, search and tick these policies:
   - `AmazonEKSClusterPolicy`
   - `AmazonEC2ContainerRegistryFullAccess`
   - `AmazonVPCFullAccess`
   - `AWSCloudFormationFullAccess`
   - `IAMFullAccess`
   > These are broad (close to admin) — fine for a short-lived learning/
   > management box, but tear it down after. Skip the deprecated
   > `AmazonEKSServicePolicy`.
6. **Next** → Name it `EKS-Management-EC2-Role` → **Create role**.

### Step 0.2 — Attach the role to your EC2
1. Console → **EC2** → **Instances**.
2. Select your management instance.
3. **Actions** → **Security** → **Modify IAM role**.
4. Choose `EKS-Management-EC2-Role` → **Update IAM role**.
5. Confirm it attached: with the instance selected, open the **Security** tab —
   under **IAM role** you should see `EKS-Management-EC2-Role`.

### Step 0.2.5 — IMPORTANT: make sure static keys aren't shadowing the role
Attaching the role is NOT enough if the box also has static AWS keys for some
IAM **user** — static keys WIN over the instance role in the AWS credential
chain, so the role you attached gets ignored. Symptom you'll hit later:

```
eksctl create cluster -f eks.yaml
Error: ... User: arn:aws:iam::589389425618:user/vosukula-eks is not
authorized to perform: eks:DescribeClusterVersions ...
```
(It says **User:** `.../user/<name>` — proof it's using static user keys, not
the attached role.)

**Detect and fix it (SSH into the EC2 — this part is terminal, no console):**
```bash
# 1. who is the box authenticating as right now?
aws sts get-caller-identity
#    If Arn shows  .../user/vosukula-eks   -> static keys are in use (WRONG).
#    You want it to show  .../assumed-role/EKS-Management-EC2-Role/i-xxxx

# 2. find the static keys (check as the user you're logged in as, often root)
aws configure list
cat ~/.aws/credentials 2>/dev/null
cat /root/.aws/credentials 2>/dev/null
cat /home/ec2-user/.aws/credentials 2>/dev/null
env | grep AWS

# 3. remove them so the attached INSTANCE ROLE is used instead
rm -f ~/.aws/credentials ~/.aws/config
rm -f /root/.aws/credentials /home/ec2-user/.aws/credentials 2>/dev/null
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION

# 4. verify the role is now in use
aws sts get-caller-identity
#    Arn should now be: arn:aws:sts::589389425618:assumed-role/EKS-Management-EC2-Role/i-xxxx
```
Only once `get-caller-identity` shows **assumed-role/EKS-Management-EC2-Role**
will `eksctl`/`kubectl` work with the permissions you attached in Step 0.1.

> Why this happens: the AWS SDK/CLI credential order is env vars →
> `~/.aws/credentials` → **then** the EC2 instance role. If any of the first
> two exist, the instance role is never reached. Removing them lets the role
> take over.

> Alternative (if you must keep the `vosukula-eks` user keys): instead of
> removing them, give THAT user the same permissions — Console → IAM → Users →
> `vosukula-eks` → Add permissions → attach `AmazonEKSClusterPolicy`,
> `AmazonEC2FullAccess`, `AWSCloudFormationFullAccess`, `IAMFullAccess`, and an
> inline policy allowing `eks:*`. But using the instance role (above) is the
> cleaner, no-static-keys approach.

### Step 0.3 — Tools on the EC2
SSH into the instance and install `aws` CLI, `kubectl`, `eksctl`, `helm`, `git`,
`docker`. (Tool installs are commands even in the "console" path — there's no
web UI for them; see RUNBOOK-2-CLI Step 0.3 for the exact install commands.)

---

## STAGE 1 — Infrastructure (Console)

### Step 1.1 — Create the VPC
1. Console → **VPC** → **Create VPC**.
2. Select **VPC and more**.
3. Name tag `autoflow`, IPv4 CIDR `10.50.0.0/16`.
4. Number of AZs **2**; public subnets **2**; private subnets **2**.
5. NAT gateways **In 1 AZ** (cheaper for a demo).
6. **Create VPC**. Wait until all resources show created.

### Step 1.2 — Create the EKS cluster
1. Console → **EKS** → **Clusters** → **Create cluster**.
2. Name `autoflow-cluster`, Kubernetes version `1.31`.
3. **Cluster service role** → if none exists, click the link to create one in
   IAM with `AmazonEKSClusterPolicy` (trusted entity = EKS), then come back and
   select it.
4. **Next** → Networking → choose the `autoflow` VPC and its **private**
   subnets, cluster endpoint access **Public**.
5. **Next** through add-ons (defaults are fine) → **Create**.
6. Wait ~10 minutes until the cluster shows **Active**.

### Step 1.3 — Add a node group
1. Open `autoflow-cluster` → **Compute** tab → **Add node group**.
2. Name `default`.
3. **Node IAM role** → create one in IAM (trusted = EC2) with:
   `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`,
   `AmazonEC2ContainerRegistryReadOnly`. Select it.
4. **Next** → Instance type `t3.medium`, Desired `2`, Min `1`, Max `3`.
5. **Next** → choose the private subnets → **Create**.
6. Wait until nodes show **Ready**.

### Step 1.4 — Create the ECR repository
1. Console → **ECR** → **Repositories** → **Create repository**.
2. Visibility **Private**, name `demo-app` → **Create repository**.

### Step 1.5 — Create the GitHub OIDC identity provider (once per account)
1. Console → **IAM** → **Identity providers** → **Add provider**.
2. Type **OpenID Connect**.
3. Provider URL `https://token.actions.githubusercontent.com` → **Get thumbprint**.
4. Audience `sts.amazonaws.com` → **Add provider**.
   > If it already exists, skip — only one per account.

### Step 1.6 — Create the CI role (GitHub Actions assumes this)
1. IAM → **Roles** → **Create role** → **Web identity**.
2. Identity provider `token.actions.githubusercontent.com`, Audience
   `sts.amazonaws.com`.
3. **Next** → attach `AmazonEC2ContainerRegistryFullAccess` (or a scoped ECR
   push policy) → **Next**.
4. Name `autoflow-github-ci` → **Create role**.
5. Open the role → **Trust relationships** → **Edit trust policy** → set the
   `token.actions.githubusercontent.com:sub` condition to your repo, e.g.
   `repo:ShivaKrishna44/Automated-Devops-flow-end-to-end:*` → **Update**.

---

## STAGE 2 — Connect to the cluster
No console step. In the EC2 terminal run `aws eks update-kubeconfig ...` (see
RUNBOOK-2-CLI Step 2) — kubectl always talks to the cluster from a terminal.
You can **confirm** the cluster is Active and nodes Ready in EKS → cluster →
**Compute**.

---

## STAGE 3 — CI/CD (GitHub web console)

### Step 3.1 — Push the repo to GitHub
Create the repo `ShivaKrishna44/Automated-Devops-flow-end-to-end` on GitHub
(web: **New repository**), then push your code (git commands in RUNBOOK-2-CLI).

### Step 3.2 — Set the Actions variables
1. GitHub repo → **Settings** → **Secrets and variables** → **Actions**.
2. **Variables** tab → **New repository variable**:
   - Name `AWS_ROLE_ARN`, value `arn:aws:iam::589389425618:role/autoflow-github-ci`.
   - **New repository variable** again: Name `ECR_REGISTRY`, value
     `589389425618.dkr.ecr.us-east-1.amazonaws.com`.

### Step 3.3 — Run the pipeline
1. Repo → **Actions** tab.
2. Select the **CI** workflow on the left.
3. **Run workflow** → **Run workflow**. (Or push a commit under `app/**`.)

### Step 3.4 — Watch it
1. Click the running workflow run.
2. Expand each step:
   - **Configure AWS credentials (OIDC)** — must authenticate.
   - **Login to ECR**, **Build & push** — image pushed.
   - **Update Helm values** — commits the new tag.
   > If OIDC auth fails with **AccessDenied**, the role's `sub` doesn't match —
   > fix it in IAM → role → Trust relationships (see RUNBOOK-2-CLI for the
   > CloudTrail lookup to get the exact value).

### Step 3.5 — Confirm the image
1. Console → **ECR** → `demo-app` → see the pushed image + tag.

---

## STAGE 4 — Deploy with ArgoCD

### Step 4.1 — Install ArgoCD
No AWS console step (it runs inside the cluster). Install it from the terminal
(RUNBOOK-2-CLI Step 4.1), then use ArgoCD's **own web UI** below.

### Step 4.2 — Open the ArgoCD UI
1. From the terminal, port-forward the ArgoCD server (RUNBOOK-2-CLI Step 4.2).
2. Browser → `https://localhost:8081`.
3. Login: username `admin`, password = the initial admin secret (get it from
   the terminal, RUNBOOK-2-CLI Step 4.2).

### Step 4.3 — Create the Application (deploy the app)
1. In the ArgoCD UI → **+ NEW APP**.
2. Application Name `demo-app`, Project `default`, Sync Policy **Automatic**.
3. **Source** → Repo URL
   `https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git`,
   Revision `main`, Path `charts/demo-app`.
4. **Destination** → Cluster URL `https://kubernetes.default.svc`, Namespace
   `default`.
5. **CREATE**.
6. Watch the app tile go **Synced / Healthy** (click it to see the resource
   tree: Deployment → ReplicaSet → Pods → Service turning green).

---

## STAGE 5 — Monitoring (Grafana / Prometheus web UIs)

### Step 5.1 — Install the monitoring stack
No AWS console step (Helm installs it in-cluster). Terminal: RUNBOOK-2-CLI
Step 5.1. Then use the UIs below.

### Step 5.2 — Open Grafana
1. From the terminal, port-forward Grafana (RUNBOOK-2-CLI Step 5.2).
2. Browser → `http://localhost:3000`.
3. Login `admin` + the Grafana admin password (from the terminal).
4. Left menu → **Dashboards** → open a built-in **Kubernetes** dashboard →
   see cluster CPU/memory/pods/nodes graphs.

### Step 5.3 — Open Prometheus (optional)
1. Port-forward Prometheus (RUNBOOK-2-CLI Step 5.3).
2. Browser → `http://localhost:9090`.
3. **Status** → **Targets** → confirm targets are **UP**.
4. In the query box type `up` → **Execute** → see results.

---

## STAGE 6 — Verify + Teardown (Console)

### Verify (open each console)
- **EKS** → cluster **Active**, nodes **Ready**.
- **ECR** → `demo-app` image present.
- **GitHub Actions** → latest run green.
- **ArgoCD UI** → `demo-app` Synced / Healthy.
- **Grafana** → dashboards showing data.

### Teardown (delete app/monitoring FIRST, then infra)
1. **ArgoCD UI** → open `demo-app` → **DELETE** the application.
2. Terminal: `helm uninstall monitoring -n monitoring` (no console for Helm).
3. **EKS** → cluster → **Compute** → delete the **node group** (wait till gone)
   → then delete the **cluster**.
4. **ECR** → delete the `demo-app` repository.
5. **EC2** → **Load Balancers** → delete any ALB created by the app/ingress
   (do this or it keeps billing you).
6. **VPC** → delete the `autoflow` VPC (deletes subnets/NAT/IGW with it).
7. **CloudWatch** → **Log groups** → delete `/aws/eks/autoflow-cluster/cluster`.
8. **KMS** → delete alias `alias/eks/autoflow-cluster`.
9. **IAM** → delete the roles you created if you're done
   (`EKS-Management-EC2-Role`, node role, `autoflow-github-ci`).

> Order matters: delete the app + its load balancer BEFORE the cluster, or you
> get an orphaned ALB that keeps costing money.
