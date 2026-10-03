# IRSA Hands-On Lab — watch a pod assume an IAM role with NO keys

Goal: see, for real, a Kubernetes pod call AWS using an IAM role it got via the
cluster's **OIDC provider** — no access keys anywhere — and prove the role is
scoped to exactly one ServiceAccount.

Cluster: `autoflow-cluster` (us-east-1), OIDC issuer
`oidc.eks.us-east-1.amazonaws.com/id/4D8AF22CB6D9EFE42A4AAA79B54D5448`.

---

## The concept in one picture

```
Pod (uses ServiceAccount "irsa-demo-sa")
  │  the SA is annotated: eks.amazonaws.com/role-arn: <role>
  ▼
EKS injects a short-lived OIDC token (a JWT) into the pod
  │  the token's `sub` claim = system:serviceaccount:default:irsa-demo-sa
  ▼
Pod calls sts:AssumeRoleWithWebIdentity with that token
  │
  ▼
IAM checks the role's TRUST POLICY:
   - is the token from an OIDC provider I trust?   (issuer match)
   - is `aud` == sts.amazonaws.com?                (audience match)
   - is `sub` == system:serviceaccount:default:irsa-demo-sa?  (subject match)
  │  all three must pass
  ▼
IAM hands back TEMPORARY credentials for the role
  ▼
Pod uses them to call S3 — scoped to exactly what the role's policy allows
```

This is the **same mechanism** as GitHub Actions → AWS (see
`../terraform/github-oidc.tf`). Only the issuer and the `sub` format differ
(K8s ServiceAccount here vs GitHub repo there).

---

## Step 0 — prerequisites (already done)

- Cluster running, `kubectl` pointed at it:
  ```bash
  aws eks update-kubeconfig --name autoflow-cluster --region us-east-1
  kubectl get nodes            # 2 nodes Ready
  ```
- The cluster has an OIDC provider (your Terraform set `enable_irsa = true`).
  Confirm it exists in IAM:
  ```bash
  aws iam list-open-id-connect-providers
  # should list .../oidc.eks.us-east-1.amazonaws.com/id/4D8AF22C...
  ```

---

## Step 1 — create the IAM role + bucket (Terraform)

```bash
cd irsa-lab
terraform init
terraform apply        # creates: S3 bucket + sample object, IAM policy, IRSA role
```
Grab the outputs:
```bash
terraform output -raw role_arn        # e.g. arn:aws:iam::589389425618:role/irsa-lab-demo-role
terraform output -raw bucket_name     # e.g. irsa-lab-589389425618-demo
```

**Look at what the trust policy actually says** — this is the whole lesson:
```bash
aws iam get-role --role-name irsa-lab-demo-role --query "Role.AssumeRolePolicyDocument"
```
You'll see `AssumeRoleWithWebIdentity`, a `Federated` principal = your cluster's
OIDC provider, and a condition that `...:sub` must equal
`system:serviceaccount:default:irsa-demo-sa`. **Only pods running as that exact
ServiceAccount can assume this role.** Nothing else.

---

## Step 2 — create the ServiceAccount (annotated with the role)

Put the real role ARN into `serviceaccount.yaml` (replace the placeholder with
the `role_arn` output), then:
```bash
kubectl apply -f serviceaccount.yaml
kubectl get sa irsa-demo-sa -o yaml    # confirm the eks.amazonaws.com/role-arn annotation
```
The annotation is the link: EKS's pod-identity webhook sees it and auto-injects
the OIDC token + `AWS_ROLE_ARN` into any pod using this SA.

---

## Step 3 — run the test pods

```bash
kubectl apply -f test-pods.yaml
kubectl get pods          # wait for irsa-pod AND no-irsa-pod to be Running
```

---

## Step 4 — PROVE it: the pod WITH the ServiceAccount assumes the role

```bash
# Who am I, according to AWS, from inside the pod?
kubectl exec -it irsa-pod -- aws sts get-caller-identity
```
**Observe:** the ARN returned is the ASSUMED ROLE
`arn:aws:sts::...:assumed-role/irsa-lab-demo-role/...` — NOT a node role, NOT a
user. The pod got role credentials purely from the OIDC token. No keys were set.

```bash
# Read the allowed bucket — should WORK:
kubectl exec -it irsa-pod -- aws s3 ls s3://<bucket_name>
kubectl exec -it irsa-pod -- aws s3 cp s3://<bucket_name>/hello.txt -

# Read some OTHER bucket — should be DENIED (policy only grants the one bucket):
kubectl exec -it irsa-pod -- aws s3 ls s3://some-bucket-you-dont-own 2>&1 | head
```
**Observe:** allowed bucket works, other bucket = `AccessDenied`. The role's
policy scoped it to exactly one bucket.

**Peek at HOW the creds got in** (the injected token + env):
```bash
kubectl exec -it irsa-pod -- env | grep AWS
# AWS_ROLE_ARN=..., AWS_WEB_IDENTITY_TOKEN_FILE=/var/run/secrets/.../token
kubectl exec -it irsa-pod -- cat /var/run/secrets/eks.amazonaws.com/serviceaccount/token
# a JWT — paste its middle segment into jwt.io / base64 -d to see sub & aud
```

---

## Step 5 — PROVE scoping: the pod WITHOUT the ServiceAccount CANNOT

```bash
kubectl exec -it no-irsa-pod -- aws sts get-caller-identity 2>&1 | head
```
**Observe:** this fails (or returns the node's identity, not the demo role) —
because this pod uses the `default` SA, which has no role annotation, so no
OIDC token for `irsa-demo-sa` is injected, so it can't assume the role. The
trust policy's `sub` condition would reject it even if it tried.

That contrast — same cluster, same nodes, one pod can and one can't — IS IRSA:
AWS access is granted per-ServiceAccount, not per-node.

---

## Step 6 — connect it to GitHub Actions OIDC (the "it's the same thing" moment)

Open `../terraform/github-oidc.tf` and compare the two trust policies:

```
IRSA (this lab):
  Principal.Federated = <cluster OIDC provider>
  Action              = sts:AssumeRoleWithWebIdentity
  Condition sub       = system:serviceaccount:default:irsa-demo-sa
  Condition aud       = sts.amazonaws.com

GitHub Actions OIDC:
  Principal.Federated = token.actions.githubusercontent.com provider
  Action              = sts:AssumeRoleWithWebIdentity
  Condition sub       = repo:<owner>/<repo>:ref:refs/heads/main
  Condition aud       = sts.amazonaws.com
```
**Identical pattern.** A workload proves its identity with a short-lived OIDC
token; AWS checks issuer + `aud` + `sub` against a trust policy and hands back
temporary creds. Pod or pipeline — same mechanism. Once you've done this lab,
you understand both.

---

## Teardown (do this — the bucket + role cost ~nothing but clean up anyway)

```bash
kubectl delete -f test-pods.yaml -f serviceaccount.yaml
cd irsa-lab && terraform destroy
```
(The main `autoflow-cluster` is separate — this only removes the lab's bucket,
policy, and role.)

---

## What to be able to say in an interview afterward

> "IRSA lets a specific Kubernetes ServiceAccount assume a specific IAM role via
> the cluster's OIDC provider — no static keys. The role's trust policy
> conditions on the OIDC token's `sub` claim being exactly
> `system:serviceaccount:<ns>:<name>` and `aud` being `sts.amazonaws.com`. I've
> verified it hands-on: a pod with the annotated ServiceAccount got assumed-role
> creds and could read only its allowed bucket, while a pod without it couldn't
> assume the role at all. It's the same `AssumeRoleWithWebIdentity` + trust-policy
> mechanism GitHub Actions uses to reach AWS — just a different issuer and `sub`."
