"""The n8n side of the human-in-the-loop guarantee, checked on the exported workflow JSON.

- every connection points at a node that exists, node names are unique;
- the nodes that call out (HTTP, email, Telegram) retry three times before the error workflow fires;
- no credential data, token or key is embedded in the files;
- the only path to the "Send reply" node runs through the decision call and the "approved or edited"
  branch, and the intake workflow has no email node at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / "workflows").glob("*.json"))
RETRYING_TYPES = {
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.telegram",
    "n8n-nodes-base.googleSheets",
}
SECRET_RE = re.compile(
    r"(?i)(?:\d{6,}:[A-Za-z0-9_-]{30,}|sk-ant-|pat-[a-z0-9-]{20,}|\"password\"\s*:\s*\"[^\"]+\")"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def edges(wf: dict) -> list[tuple[str, str, int]]:
    out = []
    for src, by_type in wf["connections"].items():
        for outputs in by_type.values():
            for index, targets in enumerate(outputs):
                for t in targets or []:
                    out.append((src, t["node"], index))
    return out


def predecessors(wf: dict, name: str) -> set[str]:
    seen, stack = set(), [name]
    while stack:
        current = stack.pop()
        for src, dst, _ in edges(wf):
            if dst == current and src not in seen:
                seen.add(src)
                stack.append(src)
    return seen


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.stem for p in WORKFLOWS])
def test_workflow_is_well_formed(path):
    wf = load(path)
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names)), "node names must be unique"
    for src, dst, _ in edges(wf):
        assert src in names and dst in names, f"dangling connection {src} -> {dst}"
    for node in wf["nodes"]:
        assert node["type"].startswith("n8n-nodes-base."), node["name"]
        if node["type"] in RETRYING_TYPES and not node.get("disabled"):
            assert node.get("retryOnFail") is True, f"{node['name']} must retry"
            assert node.get("maxTries") == 3, f"{node['name']} must retry 3 times"
        for cred in (node.get("credentials") or {}).values():
            assert set(cred) <= {"id", "name"}, "credentials are referenced by id only"


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.stem for p in WORKFLOWS])
def test_no_secrets_in_workflow_files(path):
    text = path.read_text(encoding="utf-8")
    assert not SECRET_RE.search(text), "a token or password is embedded in the workflow"


def test_intake_workflow_never_sends_email():
    wf = load(ROOT / "workflows" / "lead-intake.json")
    assert all(n["type"] != "n8n-nodes-base.emailSend" for n in wf["nodes"])
    assert any(n["type"] == "n8n-nodes-base.webhook" for n in wf["nodes"])
    assert any(n["type"] == "n8n-nodes-base.telegram" for n in wf["nodes"])


def test_send_reply_is_only_reachable_through_an_approval():
    wf = load(ROOT / "workflows" / "lead-approval.json")
    send = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.emailSend")
    before = predecessors(wf, send["name"])
    assert "Record decision" in before, "the decision must be recorded in the engine first"
    assert "Approved or edited?" in before
    gate = [
        (src, dst, idx)
        for src, dst, idx in edges(wf)
        if src == "Approved or edited?" and dst == send["name"]
    ]
    assert gate == [("Approved or edited?", send["name"], 0)], "only the true branch may send"
    # and nothing else feeds the email node
    direct = {src for src, dst, _ in edges(wf) if dst == send["name"]}
    assert direct == {"Approved or edited?"}


def test_error_workflow_reports_to_engine_and_owner():
    wf = load(ROOT / "workflows" / "error-handler.json")
    types = [n["type"] for n in wf["nodes"]]
    assert "n8n-nodes-base.errorTrigger" in types
    assert "n8n-nodes-base.telegram" in types
    engine_call = next(
        n
        for n in wf["nodes"]
        if n["type"] == "n8n-nodes-base.httpRequest" and "/incidents" in n["parameters"]["url"]
    )
    assert engine_call["parameters"]["method"] == "POST"


def test_main_workflows_point_at_the_error_workflow():
    error = load(ROOT / "workflows" / "error-handler.json")
    for name in ("lead-intake.json", "lead-approval.json"):
        wf = load(ROOT / "workflows" / name)
        assert wf["settings"]["errorWorkflow"] == error["id"], name
