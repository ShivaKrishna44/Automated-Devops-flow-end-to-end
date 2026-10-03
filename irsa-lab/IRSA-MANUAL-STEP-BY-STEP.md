# IRSA — Fully Manual, Step by Step (no Terraform, by hand)

Do each step yourself and SEE what it creates. This is the best way to
understand IRSA. Every command is explained in plain words.

Account: 589389425618 · Region: us-east-1 · Cluster: autoflow-cluster
(replace these if yours differ)

---

## The idea first (read once)

A pod needs AWS access. Instead of putting keys in the pod, IRSA gives the pod
a temporary AWS identity:

  ServiceAccount (a badge)  --annotated with-->  IAM role (a locked room)
       │                                              ▲
       │ pod wears the badge                          │ trust policy says:
       ▼                                              │ "only THIS badge opens me"
  EKS injects a short-lived OIDC token (ID card) into the pod
       │
       ▼
  pod shows the token to AWS -> AWS checks the role's trust policy ->
  if the token's "sub" = the trusted ServiceAccount, AWS gives temp creds

No keys. A pod without the badge can't open the room.

---

## STEP 0 — things you already have

```bash
# point kubectl at the cluster
aws eks update-kubeconfig --name autoflow-cluster --region us-east-1
kubectl get nodes                       # nodes Ready

# your account id and the cluster's OIDC issuer (write these down)
aws sts get-caller-identity --query Account --output text
aws eks describe-cluster --name autoflow-cluster --region us-east-1 \
  --query "cluster.identity.oidc.issuer" --output text
# -> https://oidc.eks.us-east-1.amazonaws.com/id/4D8AF22CB6D9EFE42A4AAA79B54D5448
```

The OIDC provider already exists (your cluster was built with IRSA enabled).
Confirm:
```bash
aws iam list-open-id-connect-providers
```

---

## STEP 1 — make an S3 bucket (the thing the pod will read)

```bash
aws s3 mb s3://irsa-manual-589389425618-demo --region us-east-1
echo "IRSA works if a pod can read this" > hello.txt
aws s3 cp hello.txt s3://irsa-manual-589389425618-demo/
```

---

## STEP 2 — write the IAM policy (what the role is ALLOWED to do)

Create `policy.json` (read only this one bucket):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::irsa-manual-589389425618-demo",
      "arn:aws:s3:::irsa-manual-589389425618-demo/*"
    ]
  }]
}
```
Create the policy in AWS:
```bash
aws iam create-policy --policy-name irsa-manual-s3-read \
  --policy-document file://policy.json
# note the returned Policy.Arn (you'll attach it in step 4)
```

---

## STEP 3 — write the TRUST POLICY (WHO is allowed to become the role)

This is the heart of IRSA. Create `trust.json`. The `sub` line is the lock —
it says "only the ServiceAccount default:irsa-demo-sa may assume me":
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::589389425618:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/4D8AF22CB6D9EFE42A4AAA79B54D5448"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.us-east-1.amazonaws.com/id/4D8AF22CB6D9EFE42A4AAA79B54D5448:aud": "sts.amazonaws.com",
        "oidc.eks.us-east-1.amazonaws.com/id/4D8AF22CB6D9EFE42A4AAA79B54D5448:sub": "system:serviceaccount:default:irsa-demo-sa"
      }
    }
  }]
}
```
Create the role with this trust policy:
```bash
aws iam create-role --role-name irsa-manual-role \
  --assume-role-policy-document file://trust.json
```

---

## STEP 4 — attach the policy to the role

Role = WHO can assume it (trust policy) + WHAT it can do (attached policy).
```bash
aws iam attach-role-policy --role-name irsa-manual-role \
  --policy-arn arn:aws:iam::589389425618:policy/irsa-manual-s3-read
```
Look at the finished role:
```bash
aws iam get-role --role-name irsa-manual-role --query "Role.AssumeRolePolicyDocument"
```

---

## STEP 5 — create the ServiceAccount (the badge) with the role annotation

```bash
kubectl create serviceaccount irsa-demo-sa -n default

kubectl annotate serviceaccount irsa-demo-sa -n default \
  eks.amazonaws.com/role-arn=arn:aws:iam::589389425618:role/irsa-manual-role

kubectl get sa irsa-demo-sa -o yaml      # see the annotation
```

---

## STEP 6 — run a pod USING that ServiceAccount

```bash
kubectl run irsa-pod --image=amazon/aws-cli --serviceaccount=irsa-demo-sa \
  --command -- sleep 3600

# and a control pod WITHOUT the ServiceAccount
kubectl run no-irsa-pod --image=amazon/aws-cli --command -- sleep 3600

kubectl get pods      # wait for both Running
```

---

## STEP 7 — THE PROOF (what makes it click)

```bash
# 1. who is the pod, to AWS?  -> should be the ASSUMED ROLE, no keys given
kubectl exec irsa-pod -- aws sts get-caller-identity
#    Arn: arn:aws:sts::...:assumed-role/irsa-manual-role/...   <-- IRSA working

# 2. read the allowed bucket -> WORKS
kubectl exec irsa-pod -- aws s3 cp s3://irsa-manual-589389425618-demo/hello.txt -

# 3. read a different bucket -> DENIED (policy only allows the one bucket)
kubectl exec irsa-pod -- aws s3 ls s3://some-bucket-not-mine

# 4. the pod WITHOUT the badge -> can't become the role
kubectl exec no-irsa-pod -- aws sts get-caller-identity
#    NOT the irsa-manual-role (no token injected, trust policy sub won't match)
```

The contrast in #1 vs #4 — same cluster, one pod can, one can't — IS IRSA.
Access is per-ServiceAccount, not per-node, and never via stored keys.

---

## STEP 8 — clean up (by hand)

```bash
kubectl delete pod irsa-pod no-irsa-pod
kubectl delete serviceaccount irsa-demo-sa -n default
aws iam detach-role-policy --role-name irsa-manual-role \
  --policy-arn arn:aws:iam::589389425618:policy/irsa-manual-s3-read
aws iam delete-role --role-name irsa-manual-role
aws iam delete-policy --policy-arn arn:aws:iam::589389425618:policy/irsa-manual-s3-read
aws s3 rm s3://irsa-manual-589389425618-demo --recursive
aws s3 rb s3://irsa-manual-589389425618-demo
```

---

## The 3 pieces, so you never forget

| Piece | What it answers | Where |
|-------|-----------------|-------|
| **Trust policy** (on the role) | WHO can assume this role | `sub` = which ServiceAccount |
| **Permissions policy** (attached) | WHAT the role can do | e.g. read one S3 bucket |
| **ServiceAccount annotation** | links a K8s SA to the role | `eks.amazonaws.com/role-arn` |

A pod gets AWS access = it uses a ServiceAccount whose annotation points at a
role whose trust policy allows that ServiceAccount's `sub`. Break any link and
the pod gets nothing.
```
