"""
Human-approval gate for destructive/costly actions.

Design (same spirit as the guarded-eks-upgrade-agent):
  - An agent CANNOT approve its own write. Approval is a separate, human step.
  - Approvals are written to approvals.json by `approve.py` (run by a human),
    one entry per action, with an actor, timestamp, and TTL.
  - A WRITE MCP tool calls require_approval(action); it only proceeds if a
    FRESH, UNUSED approval for that exact action exists. Approvals are
    single-use (consumed on success) so one approval can't authorize repeats.
  - Everything is logged to audit.log.

This is intentionally simple file-based honor-system locally (documented
limitation). In CI the real gate is the GitHub Environment required-reviewer
on the apply job — see .github and the README.
"""

import json
import os
import time

_HERE = os.path.dirname(__file__)
STATE_DIR = os.path.join(_HERE, "..", ".state")
os.makedirs(STATE_DIR, exist_ok=True)

APPROVALS_FILE = os.path.join(STATE_DIR, "approvals.json")
AUDIT_LOG = os.path.join(STATE_DIR, "audit.log")

# How long an approval stays valid (minutes)
TTL_MINUTES = int(os.getenv("APPROVAL_TTL_MINUTES", "30"))


def _load() -> dict:
    if not os.path.exists(APPROVALS_FILE):
        return {}
    try:
        with open(APPROVALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save(data: dict) -> None:
    with open(APPROVALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def grant(action: str, actor: str) -> None:
    """Called by approve.py (human). Records a fresh, unused approval."""
    data = _load()
    data[action] = {
        "actor": actor,
        "granted_at": time.time(),
        "used": False,
    }
    _save(data)


def require_approval(action: str) -> tuple[bool, str]:
    """Called by a WRITE tool. Returns (allowed, reason). Consumes on success."""
    data = _load()
    entry = data.get(action)

    if not entry:
        return False, (
            f"No approval on record for '{action}'. A human must run: "
            f"python approve.py {action} --actor <name>"
        )
    if entry.get("used"):
        return False, f"Approval for '{action}' was already used (single-use). Re-approve to run again."

    age_min = (time.time() - entry["granted_at"]) / 60.0
    if age_min > TTL_MINUTES:
        return False, f"Approval for '{action}' expired ({age_min:.0f}m > {TTL_MINUTES}m TTL). Re-approve."

    # consume it (single-use)
    entry["used"] = True
    _save(data)
    return True, f"Approved by {entry['actor']} ({age_min:.1f}m ago), consumed."


def status() -> dict:
    """Human-readable view of current approvals."""
    return _load()
