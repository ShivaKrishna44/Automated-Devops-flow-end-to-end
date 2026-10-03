# Teardown — Destroy Everything (stop the billing)

Run this when you're done with the demo. A running EKS cluster bills
continuously (control plane ~$0.10/hr + nodes + NAT gateway ~$0.045/hr), so
don't leave it up. Follow the order — delete workloads BEFORE infra, or you get
orphaned load balancers that keep charging after the cluster is gone.

Cluster: `autoflow-cluster` · Region: `us-east-1`

---

## Step 0 — See what's actually running (so you clean up ALL of it)

```bash
# EKS clusters
aws eks list-clusters --region us-east-1

# running EC2 instances (the autoflow nodes + any practice boxes)
aws ec2 describe-instances --region us-east-1 \
  --filters "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].{ID:InstanceId,Name:Tags[?Key=='Name']|[0].Value,Type:InstanceType}" \
  --output table

# load balancers (these are the sneaky ones that outlive the cluster)
aws elbv2 describe-load-balancers --region us-east-1 \
  --query "LoadBalancers[].{Name:LoadBalancerName,DNS:DNSName}" --output table
```

> You may have MORE than one cluster billing: `autoflow-cluster` (this project)
> AND possibly `expense` (the eksctl cluster from the docker/ practice). Tear
> down every one you're not using.

---

## Step 1 — Delete the app + ArgoCD + monitoring (workloads FIRST)

Doing this before `terraform destroy` lets Kubernetes clean up any
Service/Ingress-created AWS load balancers, so none are left orphaned.

```bash
# the demo app (via its ArgoCD Application)
kubectl delete -f deploy/argocd-application.yaml

# ArgoCD itself
kubectl delete namespace argocd

# monitoring, if you installed it
helm uninstall monitoring -n monitoring 2>/dev/null
kubectl delete namespace monitoring 2>/dev/null

# metrics-server (if installed manually)
kubectl delete -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml 2>/dev/null
```

Confirm no load balancers remain from the workloads:
```bash
kubectl get svc -A | grep LoadBalancer     # should be empty
aws elbv2 describe-load-balancers --region us-east-1 --query "LoadBalancers[].LoadBalancerName" --output table
```

---

## Step 2 — Destroy the infrastructure (Terraform)

```bash
cd terraform
terraform destroy        # review the plan, type yes
```
Or via the automated path:
```bash
python run.py --teardown
# second terminal:
python approve.py terraform_destroy --actor shiva
```
This removes the EKS cluster, node group, VPC, NAT gateway, ECR, and IAM roles
Terraform created. ~10-15 min.

---

## Step 3 — Clean up what AWS leaves behind

EKS/CloudWatch keep these AFTER the cluster is deleted — delete them manually
or they linger (the log group is cheap but clutters; the KMS alias blocks
re-creating a same-named cluster later):

```bash
aws logs delete-log-group --log-group-name /aws/eks/autoflow-cluster/cluster --region us-east-1
aws kms delete-alias --alias-name alias/eks/autoflow-cluster --region us-east-1
```

If you had `delete_on_termination = false` on any volumes (not the default
here), also check for and delete orphaned EBS volumes:
```bash
aws ec2 describe-volumes --region us-east-1 \
  --filters "Name=status,Values=available" \
  --query "Volumes[].{ID:VolumeId,Size:Size}" --output table
# aws ec2 delete-volume --volume-id <vol-id> --region us-east-1   (per orphan)
```

---

## Step 4 — Tear down the OTHER clusters/boxes (if any)

**The `expense` eksctl cluster** (from the docker/ practice), if up:
```bash
eksctl delete cluster -f eks.yaml --region us-east-1
# (eksctl cleans up its own VPC/nodegroup/CloudFormation stacks)
```

**The docker practice EC2** (and any management EC2), if done:
```bash
# find it, then stop or terminate
aws ec2 terminate-instances --instance-ids <instance-id> --region us-east-1
```

---

## Step 5 — Final verification (nothing should be billing)

```bash
aws eks list-clusters --region us-east-1            # -> {"clusters": []}

aws ec2 describe-instances --region us-east-1 \
  --filters "Name=instance-state-name,Values=running" \
  --query "Reservations[].Instances[].InstanceId" --output table   # -> empty (or only boxes you want)

aws elbv2 describe-load-balancers --region us-east-1 \
  --query "LoadBalancers[].LoadBalancerName" --output table         # -> empty

# NAT gateways cost money even idle — make sure none linger
aws ec2 describe-nat-gateways --region us-east-1 \
  --filter "Name=state,Values=available" \
  --query "NatGateways[].NatGatewayId" --output table               # -> empty
```

What is NOT deleted (and is fine to keep — costs ~nothing):
- The S3 Terraform state bucket + DynamoDB lock table (reused across runs).
- The GitHub OIDC identity provider (shared; other projects use it).
- IAM roles like `EKS-Management-EC2-Role` (delete only if fully done).

---

## The teardown-order rule (why it matters)

```
workloads (app/ArgoCD/monitoring)  ->  THEN infra (terraform destroy)  ->  THEN leftovers
```
If you destroy the cluster FIRST while a Service/Ingress LoadBalancer still
exists, Kubernetes never gets to delete that ALB — it's left orphaned in AWS,
billing you, with nothing managing it. Always remove the workloads first.
