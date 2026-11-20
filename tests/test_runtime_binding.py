import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from claw_orchestrator.gateway import GatewayClient


async def test_review_device_is_separate_and_stable_per_owner(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is required for native device signing")

    class Guard:
        async def run(self, operation):
            return await operation

    state = SimpleNamespace(gateway_device_root=tmp_path)
    first = GatewayClient(state, None, {"id": uuid4()}, Guard())
    chat = await first.device("chat-challenge")
    first.scopes = ["operator.read", "operator.approvals"]
    review = await first.device("review-challenge")
    again = await first.device("new-review-challenge")
    other = GatewayClient(state, None, {"id": uuid4()}, Guard())
    other.scopes = first.scopes
    other_review = await other.device("other-owner-challenge")
    assert chat["id"] != review["id"] != other_review["id"]
    assert review["id"] == again["id"]
    assert review["signature"] != again["signature"]


@pytest.mark.parametrize("mode", ["trusted-proxy", "token"])
def test_native_startup_keeps_proxy_auth_separate_from_token_auth(tmp_path, mode):
    source = Path(".state/research/nemoclaw/scripts/nemoclaw-start.sh")
    if not source.exists() or not shutil.which("node"):
        pytest.skip("Pinned local runtime toolchain is not installed")
    function = source.read_text().split("ensure_gateway_token() {", 1)[1]
    match = re.search(r"<<'NODETOKEN'[^\n]*\n(.*?)\nNODETOKEN", function, re.S)
    assert match
    policy = {"userHeader": "x-claw-user", "allowUsers": ["user1"]}
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps(
            {
                "gateway": {"auth": {"mode": mode, "token": "old-token", "trustedProxy": policy}},
                "agents": {"defaults": {"workspace": "/sandbox/.openclaw/workspace"}},
            }
        )
    )
    subprocess.run(
        ["node", "-", str(config), "18789"],
        input=match[1],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(config.read_text())
    auth = result["gateway"]["auth"]
    assert auth["mode"] == mode
    assert auth["trustedProxy"] == policy
    assert result["agents"]["defaults"]["workspace"] == "/sandbox/.openclaw/workspace"
    if mode == "trusted-proxy":
        assert "token" not in auth
    else:
        assert auth["token"] != "old-token"
        assert len(auth["token"]) >= 32


def test_native_volume_extension_is_bound_and_preserves_other_sandboxes():
    module = Path(".state/research/nemoclaw/dist/lib/onboard/managed-startup/state-roots.js")
    if not module.exists() or not shutil.which("node"):
        pytest.skip("Pinned local runtime toolchain is not installed")
    script = """
const {managedStartupStateRoots: roots} = require(process.argv[1]);
const id='8ce7da1b-5744-4b0b-9d41-538d7fe597a1';
const input=name=>({agent:'openclaw',sandboxName:name,agentIdentity:{uid:998,gid:998}});
const normal=roots(input('my-assistant'))[0].resourceIdentity;
process.env.CLAW_ORCHESTRATOR_INSTANCE_ID=id;
const bound=roots(input('co-8ce7da1b57444b0b'))[0].resourceIdentity;
delete process.env.CLAW_ORCHESTRATOR_INSTANCE_ID;
let rejected=false;
try { roots(input('co-8ce7da1b57444b0b')); } catch { rejected=true; }
console.log(JSON.stringify({normal,bound,rejected}));
"""
    result = subprocess.run(
        ["node", "-e", script, str(module.resolve())], check=True, capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data == {
        "normal": "nemoclaw-openclaw-state-v1-my-assistant",
        "bound": "openclaw-data-8ce7da1b-5744-4b0b-9d41-538d7fe597a1",
        "rejected": True,
    }
