"""
CrewAI agents for the end-to-end flow. Each agent is scoped to one phase and
calls the MCP tools (read freely; writes are gated by the approval module).

The agents here are deliberately thin: the heavy lifting (actual terraform /
kubectl / helm calls) happens in the MCP server tools, so the agents orchestrate
and report rather than embedding shell logic. This keeps the auditable boundary
in one place (mcp_server/server.py).

NOTE on running: CrewAI requires Python 3.10–3.13 (NOT 3.14). If CrewAI isn't
installed, run.py falls back to a direct (non-LLM) orchestration path so the
flow still works — see run.py.
"""

try:
    from crewai import Agent, Task, Crew, Process
    CREWAI_AVAILABLE = True
except Exception:  # noqa: BLE001
    CREWAI_AVAILABLE = False


def build_agents(llm=None):
    """Construct the five phase agents. llm is passed through to CrewAI."""
    if not CREWAI_AVAILABLE:
        return None

    infra = Agent(
        role="Infrastructure Engineer",
        goal="Provision the EKS cluster safely via Terraform, only after approval.",
        backstory="You run terraform_plan, present it, and only call terraform_apply "
                  "once a human approval exists. You never force infra changes.",
        allow_delegation=False,
        llm=llm,
    )
    ci = Agent(
        role="CI Engineer",
        goal="Ensure the demo-app image is built and pushed to ECR by GitHub Actions.",
        backstory="You trigger/monitor the GitHub Actions pipeline and confirm the "
                  "image landed in ECR before deployment proceeds.",
        allow_delegation=False,
        llm=llm,
    )
    deploy = Agent(
        role="Deployment Engineer",
        goal="Install ArgoCD and deploy the app via GitOps.",
        backstory="You install ArgoCD and apply the Application so the cluster syncs "
                  "to the Helm chart in Git.",
        allow_delegation=False,
        llm=llm,
    )
    monitoring = Agent(
        role="Monitoring Engineer",
        goal="Install Prometheus + Grafana and confirm metrics are flowing.",
        backstory="You install the kube-prometheus-stack and verify scrape targets are up.",
        allow_delegation=False,
        llm=llm,
    )
    verify = Agent(
        role="Verification Engineer",
        goal="Confirm the whole stack is healthy end to end and report pass/fail.",
        backstory="You check nodes, pods, the ArgoCD app status, and Prometheus targets, "
                  "then give a clear PASS or FAIL with evidence.",
        allow_delegation=False,
        llm=llm,
    )
    return {"infra": infra, "ci": ci, "deploy": deploy,
            "monitoring": monitoring, "verify": verify}
