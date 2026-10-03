"""
MCP server for the Automated DevOps Flow.

This is the SINGLE, auditable boundary between the CrewAI agents and the real
world (Terraform / AWS / kubectl / ArgoCD / GitHub / Prometheus). Agents never
shell out directly — they call these declared tools.

SAFETY MODEL (read this before adding tools):
  - READ tools run freely. They only observe (plan, status, query).
  - WRITE tools (terraform apply/destroy, argocd sync, install_*) are
    DESTRUCTIVE or COSTLY. They are guarded: each one calls require_approval()
    which refuses unless an approval token for that exact action exists
    (created by the human-approval gate in approval.py). An agent CANNOT
    approve its own write — the gate is a separate, human-driven step.

  Every tool call is appended to an audit log (audit.log) with timestamp,
  tool, args summary, and whether it was allowed.

Run:  python mcp_server/server.py
Needs: aws CLI, kubectl, helm, terraform on PATH.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from fastmcp import FastMCP

# approval.py lives next to this file
sys.path.insert(0, os.path.dirname(__file__))
from approval import require_approval, AUDIT_LOG  # noqa: E402

mcp = FastMCP("Automated DevOps Flow")

TERRAFORM_DIR = os.getenv("TERRAFORM_DIR", os.path.join(os.path.dirname(__file__), "..", "terraform"))
REGION = os.getenv("AWS_REGION", "us-east-1")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run(cmd: list, cwd: str | None = None, timeout: int = 600, stream: bool = True) -> str:
    """Run a command. By default STREAMS output live to the terminal (so you
    can see long operations like `terraform apply` progressing in real time)
    while also capturing it to return. Set stream=False for quiet calls.
    Not shell=True (no injection)."""
    import time as _time
    print(f"\n$ {' '.join(cmd)}", flush=True)
    try:
        if not stream:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            return (r.stdout or "") + (r.stderr or "")

        # Stream: merge stderr into stdout, print each line as it arrives.
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        lines = []
        start = _time.time()
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)   # live to terminal
            lines.append(line)
            if _time.time() - start > timeout:
                proc.kill()
                lines.append(f"\nERROR: command exceeded {timeout}s, killed.\n")
                break
        proc.wait()
        return "".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def _audit(tool: str, allowed: bool, detail: str = "") -> None:
    line = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "allowed": allowed,
        "detail": detail[:200],
    })
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ==========================================================================
# READ TOOLS (safe — observe only, no gate)
# ==========================================================================

@mcp.tool
def terraform_plan(dummy: str = "") -> str:
    """READ: run `terraform plan` and return the plan. Changes nothing."""
    _audit("terraform_plan", True)
    _run(["terraform", "init", "-input=false"], cwd=TERRAFORM_DIR)
    return _run(["terraform", "plan", "-no-color", "-input=false"], cwd=TERRAFORM_DIR)


@mcp.tool
def cluster_health(dummy: str = "") -> str:
    """READ: node + pod status across the cluster."""
    _audit("cluster_health", True)
    nodes = _run(["kubectl", "get", "nodes", "-o", "wide"])
    pods = _run(["kubectl", "get", "pods", "-A"])
    return f"=== NODES ===\n{nodes}\n=== PODS ===\n{pods}"


@mcp.tool
def check_pods(namespace: str = "default") -> str:
    """READ: pods in a namespace."""
    _audit("check_pods", True, namespace)
    return _run(["kubectl", "get", "pods", "-n", namespace, "-o", "wide"])


@mcp.tool
def get_argocd_app_status(app_name: str = "demo-app") -> str:
    """READ: an ArgoCD Application's sync + health status."""
    _audit("get_argocd_app_status", True, app_name)
    return _run(["kubectl", "get", "application", app_name, "-n", "argocd", "-o",
                 "jsonpath={.status.sync.status}{\" / \"}{.status.health.status}"])


@mcp.tool
def query_prometheus(promql: str) -> str:
    """READ: run a PromQL query (needs a port-forward to Prometheus on :9090)."""
    _audit("query_prometheus", True, promql)
    import urllib.parse
    import urllib.request
    url = "http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.read().decode()
    except Exception as e:  # noqa: BLE001
        return f"ERROR querying Prometheus (is the port-forward up?): {e}"


@mcp.tool
def check_targets(dummy: str = "") -> str:
    """READ: which Prometheus scrape targets are down (up == 0)."""
    return query_prometheus("up == 0")


@mcp.tool
def get_terraform_output(name: str) -> str:
    """READ: a specific terraform output value (e.g. ecr_repository_url)."""
    _audit("get_terraform_output", True, name)
    return _run(["terraform", "output", "-raw", name], cwd=TERRAFORM_DIR)


@mcp.tool
def configure_kubectl(dummy: str = "") -> str:
    """READ-ish: point kubectl at the cluster via `aws eks update-kubeconfig`.
    Idempotent, no infra change — just updates the local kubeconfig so every
    subsequent kubectl/helm call targets the right cluster. Reads the cluster
    name from terraform output."""
    _audit("configure_kubectl", True)
    cluster = _run(["terraform", "output", "-raw", "cluster_name"], cwd=TERRAFORM_DIR).strip()
    if not cluster or "ERROR" in cluster:
        return f"ERROR: could not read cluster_name from terraform output: {cluster}"
    out = _run(["aws", "eks", "update-kubeconfig", "--name", cluster, "--region", REGION])
    nodes = _run(["kubectl", "get", "nodes"])
    return f"kubeconfig -> {cluster}\n{out}\n=== NODES ===\n{nodes}"


# ==========================================================================
# WRITE TOOLS (destructive/costly — each requires an approval token)
# ==========================================================================

@mcp.tool
def terraform_apply(dummy: str = "") -> str:
    """WRITE (GATED): provision infra. Creates billable AWS resources (EKS).
    Refused unless a human approved the 'terraform_apply' action."""
    ok, reason = require_approval("terraform_apply")
    if not ok:
        _audit("terraform_apply", False, reason)
        return f"BLOCKED: {reason}"
    _audit("terraform_apply", True)
    return _run(["terraform", "apply", "-auto-approve", "-input=false", "-no-color"],
                cwd=TERRAFORM_DIR, timeout=1800)


@mcp.tool
def terraform_destroy(dummy: str = "") -> str:
    """WRITE (GATED): destroy ALL demo infra. Refused unless 'terraform_destroy'
    was approved."""
    ok, reason = require_approval("terraform_destroy")
    if not ok:
        _audit("terraform_destroy", False, reason)
        return f"BLOCKED: {reason}"
    _audit("terraform_destroy", True)
    return _run(["terraform", "destroy", "-auto-approve", "-input=false", "-no-color"],
                cwd=TERRAFORM_DIR, timeout=1800)


@mcp.tool
def install_argocd(dummy: str = "") -> str:
    """WRITE (GATED): install ArgoCD into the cluster."""
    ok, reason = require_approval("install_argocd")
    if not ok:
        _audit("install_argocd", False, reason)
        return f"BLOCKED: {reason}"
    _audit("install_argocd", True)

    # Create the namespace idempotently: `create namespace` errors if it
    # already exists, so apply it from a generated manifest instead. We write
    # the manifest to a temp file and apply it (avoids needing to pipe stdin).
    import tempfile
    ns_manifest = "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: argocd\n"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
        tf.write(ns_manifest)
        ns_path = tf.name
    try:
        ns_out = _run(["kubectl", "apply", "-f", ns_path])
    finally:
        try:
            os.unlink(ns_path)
        except OSError:
            pass

    install_out = _run(
        ["kubectl", "apply", "-n", "argocd", "-f",
         "https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"],
        timeout=600,
    )
    return f"=== namespace ===\n{ns_out}\n=== argocd install ===\n{install_out}"


@mcp.tool
def argocd_sync_app(repo_url: str, app_name: str = "demo-app") -> str:
    """WRITE (GATED): apply the ArgoCD Application so it deploys the chart.
    Substitutes the real repo_url into the manifest's REPLACE_WITH_REPO_URL
    placeholder before applying."""
    ok, reason = require_approval("argocd_sync_app")
    if not ok:
        _audit("argocd_sync_app", False, reason)
        return f"BLOCKED: {reason}"
    if not repo_url or repo_url.startswith("REPLACE"):
        return "BLOCKED: a real repo_url must be provided (got placeholder/empty)."
    _audit("argocd_sync_app", True, repo_url)

    import tempfile
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "deploy", "argocd-application.yaml")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = f.read()
    manifest = manifest.replace("REPLACE_WITH_REPO_URL", repo_url)

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
        tf.write(manifest)
        tmp_path = tf.name
    try:
        return _run(["kubectl", "apply", "-f", tmp_path])
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@mcp.tool
def install_alb_controller(dummy: str = "") -> str:
    """WRITE (GATED): install the AWS Load Balancer Controller via Helm, wired
    to its IRSA role (from terraform output alb_controller_role_arn)."""
    ok, reason = require_approval("install_alb_controller")
    if not ok:
        _audit("install_alb_controller", False, reason)
        return f"BLOCKED: {reason}"
    _audit("install_alb_controller", True)

    cluster = _run(["terraform", "output", "-raw", "cluster_name"], cwd=TERRAFORM_DIR).strip()
    role_arn = _run(["terraform", "output", "-raw", "alb_controller_role_arn"], cwd=TERRAFORM_DIR).strip()
    if "ERROR" in cluster or "ERROR" in role_arn:
        return f"ERROR reading terraform outputs: cluster={cluster} role={role_arn}"

    _run(["helm", "repo", "add", "eks", "https://aws.github.io/eks-charts"])
    _run(["helm", "repo", "update"])
    return _run([
        "helm", "upgrade", "--install", "aws-load-balancer-controller",
        "eks/aws-load-balancer-controller", "-n", "kube-system",
        "--set", f"clusterName={cluster}",
        "--set", "serviceAccount.create=true",
        "--set", "serviceAccount.name=aws-load-balancer-controller",
        "--set", f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={role_arn}",
    ], timeout=600)


@mcp.tool
def install_monitoring(dummy: str = "") -> str:
    """WRITE (GATED): install kube-prometheus-stack (Prometheus+Grafana) via Helm."""
    ok, reason = require_approval("install_monitoring")
    if not ok:
        _audit("install_monitoring", False, reason)
        return f"BLOCKED: {reason}"
    _audit("install_monitoring", True)
    _run(["helm", "repo", "add", "prometheus-community",
          "https://prometheus-community.github.io/helm-charts"])
    _run(["helm", "repo", "update"])
    return _run(["helm", "upgrade", "--install", "monitoring",
                 "prometheus-community/kube-prometheus-stack",
                 "-n", "monitoring", "--create-namespace"], timeout=900)


if __name__ == "__main__":
    print("Automated DevOps Flow MCP server starting...")
    print(f"  TERRAFORM_DIR = {TERRAFORM_DIR}")
    print(f"  AWS_REGION    = {REGION}")
    print(f"  audit log     = {AUDIT_LOG}")
    mcp.run()
