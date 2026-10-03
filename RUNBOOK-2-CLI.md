# Runbook 2 — CLI (command-by-command): Infra → CI/CD → Deploy → Monitoring

Everything done from the terminal. This is the **CLI-only** version. The
matching click-by-click Console version is `RUNBOOK-1-CONSOLE.md`.

Assumes an **EC2 management instance** with an IAM role attached (no keys).
Account `589389425618`, Region `us-east-1`.

> Windows Git Bash: if a `/path`-looking argument gets mangled, prefix the
> command with `MSYS_NO_PATHCONV=1`.

---

## STAGE 0 — Management EC2 + tools

### Step 0.1 — (role attach is done in the Console, see RUNBOOK-1 Step 0.1-0.2)
Verify the instance has the role (no keys needed):
```bash
aws sts get-caller-identity
# Arn should be: arn:aws:sts::589389425618:assumed-role/EKS-Management-EC2-Role/i-xxxx
```

### Step 0.3 — Install the tools (Amazon Linux / Ubuntu)
```bash
# aws cli v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# eksctl
curl -sL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Linux_amd64.tar.gz" | tar xz
sudo mv eksctl /usr/local/bin/

# helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# git + docker
sudo yum install -y git docker || sudo apt-get install -y git docker.io
sudo systemctl enable --now docker && sudo usermod -aG docker $USER
```

---

## STAGE 1 — Infrastructure (CLI)

> A full VPC by raw `aws ec2` commands is ~15 commands. The sane CLI way is
> `eksctl`, which creates the VPC + cluster + node group in one shot. Both
> shown: eksctl (recommended) and raw aws (for understanding).

### Step 1 (recommended) — one eksctl command does VPC + cluster + nodes
```bash
eksctl create cluster \
  --name autoflow-cluster \
  --region us-east-1 \
  --version 1.31 \
  --vpc-cidr 10.50.0.0/16 \
  --nodegroup-name default \
  --node-type t3.medium \
  --nodes 2 --nodes-min 1 --nodes-max 3 \
  --managed \
  --with-oidc            # <- also creates the cluster OIDC provider (for IRSA)
# ~15 min. This also updates your kubeconfig automatically.
```

### Step 1 (raw aws, to understand the pieces) — only if NOT using eksctl
```bash
# cluster role
aws iam create-role --role-name autoflow-eks-cluster \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"eks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name autoflow-eks-cluster \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy

# cluster (needs 2 subnet IDs in your VPC)
aws eks create-cluster --name autoflow-cluster --kubernetes-version 1.31 \
  --role-arn arn:aws:iam::589389425618:role/autoflow-eks-cluster \
  --resources-vpc-config subnetIds=<subnet-a>,<subnet-b>,endpointPublicAccess=true
aws eks wait cluster-active --name autoflow-cluster

# node role (3 policies)
aws iam create-role --role-name autoflow-node \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
for p in AmazonEKSWorkerNodePolicy AmazonEKS_CNI_Policy AmazonEC2ContainerRegistryReadOnly; do
  aws iam attach-role-policy --role-name autoflow-node --policy-arn arn:aws:iam::aws:policy/$p
done

# node group
aws eks create-nodegroup --cluster-name autoflow-cluster --nodegroup-name default \
  --node-role arn:aws:iam::589389425618:role/autoflow-node \
  --subnets <subnet-a> <subnet-b> --instance-types t3.medium \
  --scaling-config minSize=1,maxSize=3,desiredSize=2
aws eks wait nodegroup-active --cluster-name autoflow-cluster --nodegroup-name default
```

### Step 1.4 — ECR repo
```bash
aws ecr create-repository --repository-name demo-app --region us-east-1
```

### Step 1.5 — GitHub OIDC provider (skip if it exists)
```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### Step 1.6 — CI role for GitHub Actions
```bash
# trust policy (scope sub to your repo)
cat > gh-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::589389425618:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:ShivaKrishna44/Automated-Devops-flow-end-to-end:*" }
    }
  }]
}
EOF
aws iam create-role --role-name autoflow-github-ci --assume-role-policy-document file://gh-trust.json
aws iam attach-role-policy --role-name autoflow-github-ci \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess
```

---

## STAGE 2 — Connect kubectl
```bash
aws eks update-kubeconfig --name autoflow-cluster --region us-east-1
kubectl get nodes          # nodes Ready
```
(eksctl already did this if you used it in Stage 1.)

---

## STAGE 3 — CI/CD (git + gh CLI)

### Step 3.1 — Push the repo
```bash
git init
git add -A
git commit -m "automated devops flow"
git branch -M main
git remote add origin https://github.com/ShivaKrishna44/Automated-Devops-flow-end-to-end.git
git push -u origin main
```

### Step 3.2 — Set Actions variables (needs the gh CLI, authed via `gh auth login`)
```bash
gh variable set AWS_ROLE_ARN -b "arn:aws:iam::589389425618:role/autoflow-github-ci"
gh variable set ECR_REGISTRY -b "589389425618.dkr.ecr.us-east-1.amazonaws.com"
```

### Step 3.3 — Trigger + watch
```bash
gh workflow run ci.yml          # or just the push above
gh run watch                    # live status
```

### Step 3.4 — If OIDC auth fails (AccessDenied), get the real sub
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 1 --region us-east-1 --query 'Events[0].CloudTrailEvent'
# read userIdentity.principalId -> the ...:sub value. Put it in the role trust
# policy's StringLike for :sub, then re-run. (immutable-ID format for new repos.)
```

### Step 3.5 — Confirm the image + pull the tag commit
```bash
aws ecr describe-images --repository-name demo-app --region us-east-1 \
  --query "imageDetails[].imageTags" --output table
git pull                        # get the CI-committed image tag in values.yaml
```

---

## STAGE 4 — Deploy with ArgoCD

### Step 4.1 — Install ArgoCD
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
```

### Step 4.2 — Get the password + open the UI
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
kubectl port-forward svc/argocd-server -n argocd 8081:443
# browser: https://localhost:8081  (login admin + that password)
```

### Step 4.3 — Deploy the app (apply the Application manifest)
```bash
# edit deploy/argocd-application.yaml -> set repoURL to your repo, then:
kubectl apply -f deploy/argocd-application.yaml
kubectl get applications -n argocd       # demo-app -> Synced / Healthy
kubectl get pods                         # demo-app pods Running
```

### Step 4.4 — Reach the app
```bash
kubectl port-forward svc/demo-app 8080:80
curl http://localhost:8080/              # {"service":"demo-app","status":"running",...}
```

---

## STAGE 5 — Monitoring

### Step 5.1 — Install Prometheus + Grafana
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace
kubectl get pods -n monitoring           # wait all Running
```

### Step 5.2 — Open Grafana
```bash
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d; echo
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
# browser: http://localhost:3000 (admin + that password) -> Dashboards -> Kubernetes
```

### Step 5.3 — Open Prometheus (optional)
```bash
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090
# browser: http://localhost:9090 -> Status > Targets ; query: up
```

---

## STAGE 6 — Verify + Teardown

### Verify
```bash
kubectl get nodes
kubectl get applications -n argocd
kubectl get pods -A
kubectl port-forward svc/demo-app 8080:80 & curl http://localhost:8080/
```

### Teardown (app/monitoring FIRST, then infra)
```bash
kubectl delete -f deploy/argocd-application.yaml
helm uninstall monitoring -n monitoring
kubectl delete namespace argocd monitoring

# if you used eksctl to create everything:
eksctl delete cluster --name autoflow-cluster --region us-east-1
# (eksctl cleans up the VPC/nodegroup/OIDC it created)

# if you used raw aws / terraform, delete nodegroup then cluster then VPC, e.g.:
#   aws eks delete-nodegroup --cluster-name autoflow-cluster --nodegroup-name default --region us-east-1
#   aws eks delete-cluster --name autoflow-cluster --region us-east-1

# leftovers AWS keeps after cluster delete:
aws logs delete-log-group --log-group-name /aws/eks/autoflow-cluster/cluster --region us-east-1
aws kms delete-alias --alias-name alias/eks/autoflow-cluster --region us-east-1

# ECR + roles if fully done:
aws ecr delete-repository --repository-name demo-app --force --region us-east-1
```

> Delete the app + its LoadBalancer BEFORE the cluster, or an orphaned ALB
> keeps billing you. Check EC2 → Load Balancers after teardown.
