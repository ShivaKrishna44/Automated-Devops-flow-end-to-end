# Live Run Notes — Real End-to-End Run (lessons + fixes)

A record of an ACTUAL run of this project on a live AWS account
(589389425618, us-east-1, cluster `autoflow-cluster`). Captures every hurdle
hit and how it was fixed — so the next run is smooth. (Separate from
`debugs.md`, which is kept as-is.)

Outcome: **full chain worked** — Terraform infra → CI built & pushed image to
ECR → ArgoCD pulled the chart from Git → app deployed and reachable on the
cluster.

```
kubectl get pods
NAME                       READY   STATUS    RESTARTS   AGE
demo-app-664cc4885-j5rtw   1/1     Running   0          12m
demo-app-664cc4885-tb8xw   1/1     Running   0          12m
# curl http://localhost:8080/  (via port-forward) -> app responds
```

---

## Issues hit, in order, and the fix for each

### 1. `kubectl` → "connection to localhost:8080 refused"
**Cause:** kubectl had no kubeconfig yet (no cluster context).
**Fix:** `aws eks update-kubeconfig --name <cluster> --region us-east-1`
(or let eksctl/run.py's Phase 1 do it automatically).

### 2. eksctl / aws → `AccessDenied` as `user/vosukula-eks`
**Cause:** static IAM-user keys on the box were SHADOWING the attached EC2
instance role (static creds win in the AWS credential chain).
**Fix:** remove the static creds so the instance role is used:
```bash
rm -f ~/.aws/credentials /root/.aws/credentials
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sts get-caller-identity   # must show assumed-role/<EC2-role>, not user/...
```
Lesson: attaching a role isn't enough if static keys exist — they override it.

### 3. `run.py` crash — `UnicodeEncodeError: '\u23f8'`
**Cause:** the script printed Unicode glyphs (⏸ ✅ —) that Windows cp1252
terminals can't encode.
**Fix:** replaced all non-ASCII characters in `run.py` with plain ASCII
(`[PAUSE]`, `[DONE]`, `-`).

### 4. `terraform apply` ran silently for ~15 min (no feedback)
**Cause:** the MCP `_run()` helper used `capture_output=True` (buffered until
done).
**Fix:** rewrote `_run()` to STREAM output line-by-line live to the terminal,
so every command (terraform/kubectl/helm) now shows real-time progress.

### 5. First automated run collided with an existing/half cluster
**Cause:** running the full flow when infra already (partly) existed →
duplicate-name 409s.
**Fix:** use `--skip-infra` once infra exists; and the GitHub OIDC provider is
now a `data` source (reference, not create) so it never 409s mid-apply.

### 6. `approve.py install_alb_controller` → "invalid choice"
**Cause:** the ALB tool was added to the server + run.py but NOT to
approve.py's allowed-actions list.
**Fix:** added `install_alb_controller` to `approve.py`'s `ACTIONS` dict.

### 7. CI "Configure AWS credentials (OIDC)" → empty AWS_ROLE_ARN / ECR_REGISTRY
**Cause (repeated):** the GitHub Actions **Variables** were set wrong:
- put in an **Environment** instead of **Repository** variables,
- and the whole `NAME = value` string was pasted into the **Value** box, with
  the Name box set to something random (`AWS`, `ENDTOEND`).
**Fix:** repo → Settings → Secrets and variables → **Actions → Variables tab**
→ two **repository** variables, Name box = key only, Value box = data only:
| Name | Value |
|------|-------|
| `AWS_ROLE_ARN` | `arn:aws:iam::589389425618:role/autoflow-github-ci` |
| `ECR_REGISTRY` | `589389425618.dkr.ecr.us-east-1.amazonaws.com` |
Lesson: `vars.X` reads **repository** variables; Name and Value are separate
fields — never paste `name = value` into the value box.

### 8. ArgoCD app = `Synced` but `Degraded` (app still works!)
**Cause:** the chart enables an HPA (`autoscaling.enabled: true`) but the
cluster has no **metrics-server**, so the HPA targets show `<unknown>` →
ArgoCD marks the app Degraded even though pods are Running.
**Fix:** install metrics-server:
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# wait ~1 min for it to start + scrape the first metrics, THEN:
kubectl top nodes    # confirms metrics-server is serving
kubectl get hpa      # TARGETS goes <unknown> -> real % (e.g. cpu: 2%/70%)
```
**Confirmed working on this run:** after ~1 min, `kubectl top nodes/pods`
returned data and the HPA showed `cpu: 2%/70%`, so ArgoCD flipped demo-app
from Degraded to Healthy. (Note: don't check `get hpa` instantly after apply —
metrics-server needs ~30-60s to start before metrics appear.)

**EKS gotcha (did NOT hit on this cluster, but common):** if `kubectl top
nodes` keeps erroring after metrics-server is Running, it's a kubelet TLS cert
issue — patch metrics-server with `--kubelet-insecure-tls`:
```bash
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
```

### 9. `run.py` exits on a blocked/declined gate (minor UX)
**Behavior:** if you press Enter before approving, the gate blocks and run.py
exits. Just re-run with `--skip-infra` and approve BEFORE pressing Enter.
**Rhythm for every gated step:** in terminal 2 run
`python approve.py <action> --actor <you>` → THEN press Enter in the run.py
terminal. (Approvals are single-use + 30-min TTL.)

---

## The approval order for a clean run (reference)

```bash
python approve.py terraform_apply        --actor shiva   # phase 0 (skip if --skip-infra)
python approve.py install_alb_controller --actor shiva   # phase 2
# phase 3 (CI): no approval — just confirm image in ECR, press Enter
python approve.py install_argocd         --actor shiva   # phase 4
python approve.py argocd_sync_app        --actor shiva   # phase 4
python approve.py install_monitoring     --actor shiva   # phase 5
```

---

## Verify the deployment

```bash
kubectl get applications -n argocd    # demo-app Synced/Healthy (Healthy after metrics-server)
kubectl get pods                      # demo-app pods Running
kubectl get svc demo-app              # ClusterIP service
kubectl port-forward svc/demo-app 8080:80
curl http://localhost:8080/           # {"service":"demo-app","status":"running",...}
```

---

## TEARDOWN (do this — it's billing now)

Delete app/monitoring first (avoid orphaned ALBs), then infra:
```bash
kubectl delete -f deploy/argocd-application.yaml      # remove the ArgoCD app
helm uninstall monitoring -n monitoring 2>/dev/null
kubectl delete namespace argocd monitoring

python run.py --teardown                              # then approve terraform_destroy
# or directly: cd terraform && terraform destroy

# leftovers AWS keeps after cluster delete:
aws logs delete-log-group --log-group-name /aws/eks/autoflow-cluster/cluster --region us-east-1
aws kms delete-alias --alias-name alias/eks/autoflow-cluster --region us-east-1
```
Also check EC2 → Load Balancers for any orphaned ALB.

> You currently have `autoflow-cluster` running (control plane + 2 nodes + NAT
> gateway). If the `expense` eksctl cluster from the docker/ practice is also
> up, that's a SECOND cluster billing — `eksctl delete cluster -f eks.yaml` it
> too when done.
