"""Pinned NemoClaw lifecycle; UUID-bound data and private Unix-socket ingress."""

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import signal
import stat
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from ..config import Settings
from .base import RuntimeResult

logger = logging.getLogger("claw_orchestrator.runtime.nemoclaw")


class NemoClawRuntime:
    def __init__(self, settings: Settings, *, validate_setup=True):
        self.settings = settings
        self.root = Path.cwd().resolve()
        self.state = self.root / ".state"
        self.source = self.state / "research/nemoclaw"
        self.binary = self.state / "bin/openshell"
        self.manifest = json.loads((self.root / "infra/runtime-versions.json").read_text())
        self.bindings = {}
        self.lock = asyncio.Lock()
        self.forwards = {}
        self.forward_locks = {}
        self.browser_bridge_locks = {}
        self.forward_inodes = {}
        self.target_ports = {}
        self.metadata = self.state / "instances"
        self.metadata.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.metadata.chmod(0o700)
        digest = hashlib.sha256(str(self.root).encode()).hexdigest()[:10]
        # macOS TMPDIR paths exceed the AF_UNIX path limit after adding a UUID.
        self.sockets = Path("/tmp") / f"co-orch-{digest}"
        self.sockets.mkdir(mode=0o700, exist_ok=True)
        if self.sockets.is_symlink() or self.sockets.stat().st_uid != os.getuid():
            raise RuntimeError("Unsafe private ingress directory")
        self.sockets.chmod(0o700)
        self.available = not validate_setup
        ready = self.state / "runtime-ready.json"
        if ready.is_file():
            self.available = (
                json.loads(ready.read_text()).get("source_revision")
                == self.manifest["nemoclaw_source_revision"]
            )
        self.reason = (
            "Your private workspace can be prepared."
            if self.available
            else "Your workspace is not available yet. Its runtime is still being configured."
        )

    def local_inference_params(self):
        extra = {"reasoning_effort": self.manifest.get("inference_reasoning_effort", "none")}
        for setting, payload in (
            ("inference_top_p", "top_p"),
            ("inference_top_k", "top_k"),
            ("inference_presence_penalty", "presence_penalty"),
        ):
            if setting in self.manifest:
                extra[payload] = self.manifest[setting]
        return {
            "temperature": self.manifest.get("inference_temperature", 0.2),
            "extra_body": extra,
        }

    def bind(self, row):
        iid = str(row["id"])
        owner = row["owner_user_id"]
        if owner not in ("user1", "user2"):
            raise RuntimeError("UNKNOWN_RUNTIME_OWNER")
        self.bindings[iid] = self.manifest["gateway_port"] + (owner == "user2")

    def gateway(self, iid):
        return f"nemoclaw-{self.bindings[iid]}"

    def environment(self, iid, *, inference_credentials=False):
        UUID(iid, version=4)
        environment = {
            **os.environ,
            "PATH": str(self.state / "bin") + os.pathsep + os.environ["PATH"],
            "NEMOCLAW_GATEWAY_PORT": str(self.bindings[iid]),
            "OPENSHELL_GATEWAY": self.gateway(iid),
            "OPENSHELL_WORKSPACE": "default",
            "NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR": str(
                self.state
                / (
                    "openshell-gateway"
                    if self.bindings[iid] == self.manifest["gateway_port"]
                    else f"openshell-gateway-{self.bindings[iid]}"
                )
            ),
            "CLAW_ORCHESTRATOR_INSTANCE_ID": iid,
            "NEMOCLAW_PROVIDER": "custom",
            "NEMOCLAW_ENDPOINT_URL": self.manifest["inference_endpoint"],
            "NEMOCLAW_MODEL": self.manifest["inference_model"],
            "NEMOCLAW_VLLM_PORT": str(urlsplit(self.manifest["inference_endpoint"]).port),
            "NEMOCLAW_COMPATIBLE_AUTH_MODE": "none",
            "NEMOCLAW_WEB_SEARCH_PROVIDER": "none",
            "NEMOCLAW_NON_INTERACTIVE": "1",
            "NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE": "1",
            "NEMOCLAW_SANDBOX_READY_TIMEOUT": "300",
            "NEMOCLAW_CPU": "2",
            "NEMOCLAW_RAM": "2Gi",
        }
        # Provider keys are needed only by native onboarding, never tenant commands.
        environment.pop("OPENROUTER_API_KEY", None)
        environment.pop("COMPATIBLE_API_KEY", None)
        environment.pop("LMSTUDIO_API_KEY", None)
        if self.settings.inference_provider == "lmstudio" and self.settings.lmstudio_api_key:
            environment.pop("NEMOCLAW_COMPATIBLE_AUTH_MODE", None)
            if inference_credentials:
                environment["COMPATIBLE_API_KEY"] = (
                    self.settings.lmstudio_api_key.get_secret_value()
                )
        if self.settings.inference_provider == "openrouter":
            for key in ("NEMOCLAW_VLLM_PORT", "NEMOCLAW_COMPATIBLE_AUTH_MODE"):
                environment.pop(key, None)
            environment.update(
                {
                    "NEMOCLAW_PROVIDER": "openrouter",
                    "NEMOCLAW_ENDPOINT_URL": self.settings.openrouter_base_url,
                    "NEMOCLAW_MODEL": self.settings.openrouter_model,
                    "NEMOCLAW_OPENROUTER_MODEL": self.settings.openrouter_model,
                }
            )
            if inference_credentials:
                key = self.settings.openrouter_api_key
                if not key or not key.get_secret_value().strip():
                    raise RuntimeError("INFERENCE_CREDENTIAL_MISSING")
                environment["OPENROUTER_API_KEY"] = key.get_secret_value()
        return environment

    async def command(
        self,
        args,
        iid,
        *,
        timeout=30,  # noqa: ASYNC109
        check=True,
        inference_credentials=False,
    ):
        proc = await asyncio.create_subprocess_exec(
            *args,
            env=self.environment(iid, inference_credentials=inference_credentials),
            cwd=self.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                out, err = await proc.communicate()
        except BaseException:
            if proc.returncode is None:
                proc.terminate()
                with suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), 5)
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            raise
        # The new provider key must not be retained even in private operator logs.
        key = self.settings.openrouter_api_key
        if key and key.get_secret_value():
            secret = key.get_secret_value().encode()
            out = out.replace(secret, b"[REDACTED_PROVIDER_KEY]")
            err = err.replace(secret, b"[REDACTED_PROVIDER_KEY]")
        local_key = self.settings.lmstudio_api_key
        if local_key and local_key.get_secret_value():
            secret = local_key.get_secret_value().encode()
            out = out.replace(secret, b"[REDACTED_PROVIDER_KEY]")
            err = err.replace(secret, b"[REDACTED_PROVIDER_KEY]")
        # Other native output remains private: it can contain paths/handshake material.
        log = self.metadata / f"{iid}.log"
        with log.open("ab") as output:
            log.chmod(0o600)
            output.write(out + err)
        if check and proc.returncode:
            raise RuntimeError("MANAGED_RUNTIME_COMMAND_FAILED")
        return out.decode() if proc.returncode == 0 else ""

    def cli(self, iid, *args):
        return [str(self.binary), "-g", self.gateway(iid), *args]

    async def sandbox(self, row):
        self.bind(row)
        iid = str(row["id"])
        text = await self.command(
            self.cli(iid, "sandbox", "get", row["sandbox_name"], "-o", "json"),
            str(row["id"]),
            check=False,
        )
        return json.loads(text) if text else None

    async def inspect(self, row, sandbox):
        iid = str(row["id"])
        if row.get("runtime_id") and row["runtime_id"] != sandbox["id"]:
            raise RuntimeError("MANAGED_RUNTIME_IDENTITY_CHANGED")
        ids = (
            await self.command(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=openshell.ai/sandbox-id={sandbox['id']}",
                ],
                iid,
            )
        ).split()
        if len(ids) != 1:
            raise RuntimeError("AMBIGUOUS_MANAGED_WORKLOAD")
        data = json.loads(await self.command(["docker", "inspect", ids[0]], iid))[0]
        labels = data["Config"].get("Labels", {})
        volume = next((m for m in data["Mounts"] if m["Destination"] == "/sandbox/.openclaw"), None)
        if (
            labels.get("openshell.ai/managed-by") != "openshell"
            or labels.get("openshell.ai/sandbox-name") != row["sandbox_name"]
            or not volume
            or volume["Type"] != "volume"
            or volume.get("Name") != row["volume_name"]
            or not volume["RW"]
            or data["HostConfig"]["Privileged"]
            or data["HostConfig"]["PortBindings"]
            or any(m["Destination"] == "/var/run/docker.sock" for m in data["Mounts"])
        ):
            raise RuntimeError("MANAGED_WORKLOAD_BOUNDARY_MISMATCH")
        info = json.loads(
            await self.command(["docker", "volume", "inspect", row["volume_name"]], iid)
        )[0]
        expected = {
            "io.nvidia.nemoclaw.openclaw-state.managed": "true",
            "io.nvidia.nemoclaw.openclaw-state.sandbox": row["sandbox_name"],
            "io.nvidia.nemoclaw.openclaw-state.target": "/sandbox/.openclaw",
        }
        if (
            info["Driver"] != "local"
            or info.get("Options")
            or any(info.get("Labels", {}).get(k) != v for k, v in expected.items())
        ):
            raise RuntimeError("DATA_VOLUME_OWNERSHIP_MISMATCH")
        return data

    async def patch_startup(self, row, data):
        """Apply the reviewed, hash-pinned compatibility fix before proxy auth.

        Native onboarding starts with token auth. Its stock restart helper must
        not add a token after this adapter selects trusted-proxy authentication.
        The managed image identity is retained; this rootfs patch is recorded
        separately and reapplied to each replacement, never to user data.
        """
        iid = str(row["id"])
        source = self.source / "scripts/nemoclaw-start.sh"
        expected = self.manifest["startup_patched_sha256"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise RuntimeError("STARTUP_PATCH_SOURCE_MISMATCH")
        temporary = f"/usr/local/bin/.nemoclaw-start-{iid}"
        await self.command(["docker", "cp", str(source), f"{data['Id']}:{temporary}"], iid)
        code = "\n".join(
            [
                "import hashlib,os",
                "from pathlib import Path",
                "target=Path('/usr/local/bin/nemoclaw-start')",
                f"temporary=Path({temporary!r})",
                "assert not target.is_symlink() and not temporary.is_symlink()",
                "current=hashlib.sha256(target.read_bytes()).hexdigest()",
                f"assert current in {[self.manifest['startup_original_sha256'], expected]!r}",
                f"assert hashlib.sha256(temporary.read_bytes()).hexdigest()=={expected!r}",
                "os.chmod(temporary,0o755); os.chown(temporary,0,0)",
                "os.replace(temporary,target)",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )

    async def configure_gateway(self, row):
        iid = str(row["id"])
        owner = row["owner_user_id"]
        policy = {
            "mode": "trusted-proxy",
            "identityScopes": {owner: ["operator.admin"]},
            "trustedProxy": {
                "userHeader": "x-claw-user",
                "allowUsers": [owner],
                "allowLoopback": True,
                "requiredHeaders": ["x-claw-proxy"],
                "deviceAutoApprove": {
                    "enabled": True,
                    "scopes": [
                        "operator.read",
                        "operator.write",
                        "operator.approvals",
                        "operator.questions",
                    ],
                },
            },
        }
        origin = self.settings.instance_origin(str(row["id"]))
        selected_model = self.manifest["inference_model"]
        context = self.manifest["inference_context_window"]
        max_tokens = self.manifest["inference_max_tokens"]
        if self.settings.inference_provider == "openrouter":
            selected_model = self.settings.openrouter_model
            context = self.settings.openrouter_context_window
            max_tokens = self.settings.openrouter_max_tokens
        code = "\n".join(
            [
                "import json,os,secrets",
                "p='/sandbox/.openclaw/openclaw.json'",
                "c=json.load(open(p)); g=c.setdefault('gateway',{})",
                "browser_password=g.get('auth',{}).get('password') or secrets.token_urlsafe(32)",
                "g['auth']=" + repr(policy),
                "g['auth']['password']=browser_password",
                "g['trustedProxies']=['127.0.0.1','::1']",
                "g.setdefault('controlUi',{})['allowedOrigins']="
                + repr([origin, self.settings.control_origin]),
                "g['publicOrigin']=" + repr(origin),
                "tools=c.setdefault('tools',{}); tools['profile']='full'",
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "c.setdefault('models',{}).setdefault('providers',{}).setdefault('inference',{})"
                "['timeoutSeconds']="
                + str(self.manifest.get("inference_request_timeout_seconds", 600)),
                "tools['loopDetection']={'enabled':True}",
                "c.setdefault('agents',{}).setdefault('defaults',{})['modelSelectionScope']='session'",
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "tools['toolSearch']={'enabled':True,'mode':'tools','searchDefaultLimit':2}",
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "c.setdefault('agents',{}).setdefault('defaults',{})['thinkingDefault']="
                + repr(self.manifest.get("inference_thinking_level", "off")),
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "c.setdefault('agents',{}).setdefault('defaults',{}).setdefault('models',{})"
                f".setdefault({'inference/' + self.manifest['inference_model']!r},{{}})"
                ".setdefault('params',{}).update(" + repr(self.local_inference_params()) + ")",
                "ex=tools.setdefault('exec',{}); ex.pop('mode',None)",
                "ex.update({'host':'gateway','security':'full','ask':'off'})",
                "for key in ['allow','deny','alsoAllow']: tools.pop(key,None)",
                "for agent in c.get('agents',{}).get('entries',{}).values():",
                " t=agent.setdefault('tools',{}); t['profile']='full'",
                " for key in ['allow','deny','alsoAllow']: t.pop(key,None)",
                " e=t.setdefault('exec',{}); e.pop('mode',None)",
                " e.update({'host':'gateway','security':'full','ask':'off'})",
                "c.setdefault('agents',{}).setdefault('defaults',{}).setdefault('heartbeat',{})['target']='none'",
                "proxy_url='http://127.0.0.1:'+str(" + str(self.settings.egress_proxy_port) + ")",
                "c.setdefault('browser',{}).update({'enabled':True,'headless':True,'executablePath':'/usr/bin/chromium','defaultProfile':'openclaw','noSandbox':True,'attachOnly':False,'extraArgs':['--proxy-server='+proxy_url,'--proxy-bypass-list=<-loopback>'],'ssrfPolicy':{'dangerouslyAllowPrivateNetwork':True}})",
                "for provider in c.get('models',{}).get('providers',{}).values():",
                " for model in provider.get('models',[]):",
                "  if model.get('id') != " + repr(selected_model) + ": continue",
                "  model['contextWindow']=" + str(context),
                "  model['maxTokens']=" + str(max_tokens),
                "with open(p+'.new','w') as f: json.dump(c,f)",
                "owner=os.stat('/sandbox/.openclaw'); os.chown(p+'.new',owner.st_uid,owner.st_gid)",
                "os.chmod(p+'.new',0o600)",
                "os.replace(p+'.new',p)",
                "print(json.dumps({'port':g.get('port',18789)}))",
            ]
        )
        output = await self.command(
            self.cli(
                iid, "sandbox", "exec", "--name", row["sandbox_name"], "--", "python3", "-c", code
            ),
            str(row["id"]),
        )
        self.target_ports[iid] = int(json.loads(output)["port"])

    async def patch_browser_navigation(self, row, data):
        """Apply pinned browser routing, snapshot and observation compatibility."""
        iid = str(row["id"])
        bundle = self.manifest["browser_navigation_bundle"]
        if Path(bundle).name != bundle:
            raise RuntimeError("INVALID_BROWSER_BUNDLE")
        original = self.manifest["browser_navigation_original_sha256"]
        patched = self.manifest["browser_navigation_patched_sha256"]
        needle = (
            "\tawait resolvePinnedHostnameWithPolicy(parsed.hostname, {\n"
            "\t\tlookupFn: opts.lookupFn,\n\t\tpolicy: opts.ssrfPolicy\n\t});"
        )
        replacement = (
            "\t// Explicit proxy owns DNS and actual connection validation "
            "in the managed sandbox.\n"
            "\t// Strict policy and direct browser connections retain the native DNS checks.\n"
            '\tif (opts.browserProxyMode === "explicit-browser-proxy" && '
            "opts.ssrfPolicy?.dangerouslyAllowPrivateNetwork === true) return;\n" + needle
        )
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"p=Path('/usr/local/lib/node_modules/openclaw/dist')/{bundle!r}",
                "assert p.is_file() and not p.is_symlink()",
                "digest=hashlib.sha256(p.read_bytes()).hexdigest()",
                f"assert digest in {[original, patched]!r}, 'Browser bundle differs from pin'",
                f"if digest=={original!r}:",
                f" source=p.read_text(); needle={needle!r}; replacement={replacement!r}",
                " assert source.count(needle)==1; result=source.replace(needle,replacement)",
                f" assert hashlib.sha256(result.encode()).hexdigest()=={patched!r}",
                " owner=p.stat(); temporary=p.with_suffix('.morrow-new')",
                " assert not temporary.is_symlink(); temporary.write_text(result)",
                " os.chmod(temporary,owner.st_mode & 0o777); "
                "os.chown(temporary,owner.st_uid,owner.st_gid); os.replace(temporary,p)",
                "print('Pinned browser proxy compatibility verified')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )
        bundle = self.manifest["browser_snapshot_bundle"]
        if Path(bundle).name != bundle:
            raise RuntimeError("INVALID_BROWSER_BUNDLE")
        original = self.manifest["browser_snapshot_original_sha256"]
        patched = self.manifest["browser_snapshot_patched_sha256"]
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"p=Path('/usr/local/lib/node_modules/openclaw/dist')/{bundle!r}",
                "assert p.is_file() and not p.is_symlink()",
                "digest=hashlib.sha256(p.read_bytes()).hexdigest()",
                f"assert digest in {[original, patched]!r}, 'Snapshot bundle differs from pin'",
                f"if digest=={original!r}:",
                " source=p.read_text(); start=source.index('const deltaFamily = plan.format')",
                " end=source.index('//#region extensions/browser/src/browser/"
                "routes/agent.storage.ts',start)",
                " section=source[start:end]; needle='ssrfPolicy: ctx.state().resolved.ssrfPolicy'",
                " assert section.count(needle)==4",
                " result=source[:start]+section.replace(needle,'...ssrfPolicyOpts')+source[end:]",
                f" assert hashlib.sha256(result.encode()).hexdigest()=={patched!r}",
                " owner=p.stat(); temporary=p.with_suffix('.morrow-new')",
                " assert not temporary.is_symlink(); temporary.write_text(result)",
                " os.chmod(temporary,owner.st_mode & 0o777); "
                "os.chown(temporary,owner.st_uid,owner.st_gid); os.replace(temporary,p)",
                "print('Pinned browser snapshot compatibility verified')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )
        bundle = self.manifest["browser_playwright_bundle"]
        if Path(bundle).name != bundle:
            raise RuntimeError("INVALID_BROWSER_BUNDLE")
        original = self.manifest["browser_playwright_original_sha256"]
        patched = self.manifest["browser_playwright_patched_sha256"]
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"p=Path('/usr/local/lib/node_modules/openclaw/dist')/{bundle!r}",
                "assert p.is_file() and not p.is_symlink()",
                "digest=hashlib.sha256(p.read_bytes()).hexdigest()",
                f"assert digest in {[original, patched]!r}, 'Playwright bundle differs from pin'",
                f"if digest=={original!r}:",
                " source=p.read_text(); "
                "start=source.index('async function prepareSnapshotPageViaPlaywright(')",
                " end=source.index('async function navigateViaPlaywright(',start)",
                " section=source[start:end]; needle='ssrfPolicy: opts.ssrfPolicy'",
                " assert section.count(needle)==4",
                " replacement='...withBrowserNavigationPolicy(opts.ssrfPolicy, "
                "{ browserProxyMode: opts.browserProxyMode })'",
                " result=source[:start]+section.replace(needle,replacement)+source[end:]",
                f" assert hashlib.sha256(result.encode()).hexdigest()=={patched!r}",
                " owner=p.stat(); temporary=p.with_suffix('.morrow-new')",
                " assert not temporary.is_symlink(); temporary.write_text(result)",
                " os.chmod(temporary,owner.st_mode & 0o777); "
                "os.chown(temporary,owner.st_uid,owner.st_gid); os.replace(temporary,p)",
                "print('Pinned Playwright snapshot compatibility verified')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )

        bundle = self.manifest["browser_observation_bundle"]
        if Path(bundle).name != bundle:
            raise RuntimeError("INVALID_BROWSER_BUNDLE")
        original = self.manifest["browser_observation_original_sha256"]
        patched = self.manifest["browser_observation_patched_sha256"]
        previous = self.manifest.get("browser_observation_previous_patched_sha256")
        changes = json.loads(
            await asyncio.to_thread(Path("infra/browser-observation-transforms.json").read_text)
        )
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"p=Path('/usr/local/lib/node_modules/openclaw/dist')/{bundle!r}",
                "assert p.is_file() and not p.is_symlink()",
                "digest=hashlib.sha256(p.read_bytes()).hexdigest()",
                f"assert digest in {[original, patched, previous]!r}, "
                "'Observation bundle differs from pin'",
                f"if digest!={patched!r}:",
                " source=p.read_text()",
                f" changes={changes!r} if digest=={original!r} else {changes[2:]!r}",
                " for needle,replacement in changes:",
                "  assert source.count(needle)==1; source=source.replace(needle,replacement)",
                f" assert hashlib.sha256(source.encode()).hexdigest()=={patched!r}",
                " owner=p.stat(); temporary=p.with_suffix('.morrow-new')",
                " assert not temporary.is_symlink(); temporary.write_text(source)",
                " os.chmod(temporary,owner.st_mode & 0o777); "
                "os.chown(temporary,owner.st_uid,owner.st_gid); os.replace(temporary,p)",
                "print('Pinned browser observation delivery verified')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )

        bundle = self.manifest["browser_catalog_bundle"]
        if Path(bundle).name != bundle:
            raise RuntimeError("INVALID_BROWSER_BUNDLE")
        original = self.manifest["browser_catalog_original_sha256"]
        patched = self.manifest["browser_catalog_patched_sha256"]
        needle = 'return classified.source === "openclaw" && (directToolNames.has(tool.name) ||'
        replacement = (
            'return classified.source === "openclaw" && '
            '((tool.name === "browser" && classified.sourceName === "browser") || '
            "directToolNames.has(tool.name) ||"
        )
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"p=Path('/usr/local/lib/node_modules/openclaw/dist')/{bundle!r}",
                "assert p.is_file() and not p.is_symlink()",
                "digest=hashlib.sha256(p.read_bytes()).hexdigest()",
                f"assert digest in {[original, patched]!r}, 'Browser bundle differs from pin'",
                f"if digest=={original!r}:",
                f" source=p.read_text(); needle={needle!r}; replacement={replacement!r}",
                " assert source.count(needle)==1; result=source.replace(needle,replacement)",
                f" assert hashlib.sha256(result.encode()).hexdigest()=={patched!r}",
                " owner=p.stat(); temporary=p.with_suffix('.morrow-new')",
                " assert not temporary.is_symlink(); temporary.write_text(result)",
                " os.chmod(temporary,owner.st_mode & 0o777); "
                "os.chown(temporary,owner.st_uid,owner.st_gid); os.replace(temporary,p)",
                "print('Pinned browser tool visibility verified')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )

    async def prepare_workspace_access(self, row):
        """Apply owner-authorized tenant-only execution policy with private backups."""
        iid = str(row["id"])
        self.bind(row)
        sandbox = await self.sandbox(row)
        data = await self.inspect(row, sandbox)
        await self.patch_browser_navigation(row, data)
        code = "\n".join(
            [
                "import json,os,shutil,time,secrets",
                "p='/sandbox/.openclaw/openclaw.json'",
                "backup='/sandbox/.openclaw/morrow-policy-backups/'+str(time.time_ns())",
                "os.makedirs(backup,mode=0o700)",
                "owner=os.stat('/sandbox/.openclaw'); "
                "os.chown(os.path.dirname(backup),owner.st_uid,owner.st_gid)",
                "os.chown(backup,owner.st_uid,owner.st_gid)",
                "shutil.copy2(p,backup+'/openclaw.json'); os.chmod(backup+'/openclaw.json',0o600)",
                "os.chown(backup+'/openclaw.json',owner.st_uid,owner.st_gid)",
                "c=json.load(open(p)); tools=c.setdefault('tools',{}); tools['profile']='full'",
                "tools['loopDetection']={'enabled':True}",
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "tools['toolSearch']={'enabled':True,'mode':'tools','searchDefaultLimit':2}",
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "c.setdefault('agents',{}).setdefault('defaults',{})['thinkingDefault']="
                + repr(self.manifest.get("inference_thinking_level", "off")),
                f"if {self.settings.inference_provider == 'lmstudio'!r}: "
                "c.setdefault('agents',{}).setdefault('defaults',{}).setdefault('models',{})"
                f".setdefault({'inference/' + self.manifest['inference_model']!r},{{}})"
                ".setdefault('params',{}).update(" + repr(self.local_inference_params()) + ")",
                "auth=c.setdefault('gateway',{}).setdefault('auth',{})",
                "auth['password']=auth.get('password') or secrets.token_urlsafe(32)",
                "ex=tools.setdefault('exec',{}); ex.pop('mode',None)",
                "ex.update({'host':'gateway','security':'full','ask':'off'})",
                "for key in ['allow','deny','alsoAllow']: tools.pop(key,None)",
                "for agent in c.get('agents',{}).get('entries',{}).values():",
                " t=agent.setdefault('tools',{}); t['profile']='full'",
                " for key in ['allow','deny','alsoAllow']: t.pop(key,None)",
                " e=t.setdefault('exec',{}); e.pop('mode',None)",
                " e.update({'host':'gateway','security':'full','ask':'off'})",
                "c.setdefault('agents',{}).setdefault('defaults',{}).setdefault('heartbeat',{})['target']='none'",
                "proxy_url='http://127.0.0.1:'+str(" + str(self.settings.egress_proxy_port) + ")",
                "c.setdefault('browser',{}).update({'enabled':True,'headless':True,'executablePath':'/usr/bin/chromium','defaultProfile':'openclaw','noSandbox':True,'attachOnly':False,'extraArgs':['--proxy-server='+proxy_url,'--proxy-bypass-list=<-loopback>'],'ssrfPolicy':{'dangerouslyAllowPrivateNetwork':True}})",
                "with open(p+'.new','w') as f: json.dump(c,f)",
                "owner=os.stat('/sandbox/.openclaw'); os.chown(p+'.new',owner.st_uid,owner.st_gid)",
                "os.chmod(p+'.new',0o600); os.replace(p+'.new',p)",
                "print('Tenant execution configuration applied')",
            ]
        )
        await self.command(["docker", "exec", data["Id"], "python3", "-c", code], iid)
        # Use the pinned native SDK transaction, not direct native-state SQL.
        script = "\n".join(
            [
                "import fs from 'node:fs';",
                "import {r as load,u as save} from "
                "'/usr/local/lib/node_modules/openclaw/dist/exec-approvals-store-DBR0neS0.js';",
                "const current=load();",
                "const dir='/sandbox/.openclaw/morrow-policy-backups/exec-'+Date.now();",
                "fs.mkdirSync(dir,{recursive:true,mode:0o700});",
                "fs.writeFileSync(dir+'/policy.json',JSON.stringify(current),{mode:0o600});",
                "current.defaults={...current.defaults,security:'full',ask:'off',askFallback:'full'};",
                "current.agents??={}; current.agents.main={...current.agents.main,"
                "security:'full',ask:'off',askFallback:'full'};",
                "save(current); const next=load();",
                "if(next.defaults.security!=='full'||next.agents.main.ask!=='off') "
                "throw Error('Policy verification failed');",
                "console.log('Native execution policy verified');",
            ]
        )
        await self.command(
            [
                "docker",
                "exec",
                "--user",
                "998",
                "--env",
                "HOME=/sandbox",
                "--env",
                "OPENCLAW_STATE_DIR=/sandbox/.openclaw",
                data["Id"],
                "node",
                "--input-type=module",
                "-e",
                script,
            ],
            iid,
        )
        await self.ensure_egress_policy(iid, row)
        await self.ensure_egress_bridge(row, data)
        await self.install_browser_guidance(row, data)
        await self.install_browser_guard(row, data)

    async def install_browser_guard(self, row, data):
        """Install the pinned, tenant-local first-navigation validation hook."""
        iid = str(row["id"])
        files = self.manifest["browser_guard_files"]
        previous = self.manifest.get("browser_guard_previous_files", {})
        if set(files) != {"index.mjs", "package.json", "openclaw.plugin.json"}:
            raise RuntimeError("INVALID_BROWSER_GUARD_ARTIFACT")
        sources = Path("infra/morrow-browser-guard")
        staged = {}
        for name, expected in files.items():
            content = await asyncio.to_thread((sources / name).read_bytes)
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError("BROWSER_GUARD_SOURCE_MISMATCH")
            staged[name] = f"/usr/local/lib/.morrow-browser-guard-{iid}-{name}"
            await self.command(
                ["docker", "cp", str(sources / name), f"{data['Id']}:{staged[name]}"], iid
            )
        code = "\n".join(
            [
                "import hashlib,json,os,shutil,time; from pathlib import Path",
                "target=Path('/usr/local/lib/morrow-browser-guard')",
                "assert not target.is_symlink()",
                "target.mkdir(mode=0o755,exist_ok=True)",
                "assert target.stat().st_uid==0 and not target.stat().st_mode & 0o022",
                f"files={files!r}; staged={staged!r}; previous={previous!r}",
                "for name,digest in files.items():",
                " p=Path(staged[name]); q=target/name",
                " assert p.is_file() and not p.is_symlink() and not q.is_symlink()",
                " assert hashlib.sha256(p.read_bytes()).hexdigest()==digest",
                " if q.exists(): assert hashlib.sha256(q.read_bytes()).hexdigest() "
                "in {digest,previous.get(name)}",
                "for name in files:",
                " p=Path(staged[name]); os.chown(p,0,0); os.chmod(p,0o644)",
                " os.replace(p,target/name)",
                "p=Path('/sandbox/.openclaw/openclaw.json'); assert not p.is_symlink()",
                "c=json.loads(p.read_text()); plugins=c.setdefault('plugins',{})",
                "paths=plugins.setdefault('load',{}).setdefault('paths',[])",
                "if str(target) not in paths: paths.append(str(target))",
                "entry=plugins.setdefault('entries',{}).setdefault('morrow-browser-guard',{})",
                "entry['enabled']=True",
                "entry.setdefault('hooks',{})['allowConversationAccess']=True",
                "if isinstance(plugins.get('allow'),list) and 'morrow-browser-guard' "
                "not in plugins['allow']: plugins['allow'].append('morrow-browser-guard')",
                "backup=str(p)+'.before-browser-guard-'+str(time.time_ns())",
                "shutil.copy2(p,backup); os.chmod(backup,0o600)",
                "q=p.with_suffix('.browser-guard'); q.write_text(json.dumps(c))",
                "owner=os.stat('/sandbox/.openclaw'); os.chown(q,owner.st_uid,owner.st_gid)",
                "os.chmod(q,0o600); os.replace(q,p)",
                "print('Pinned browser destination hook prepared; reload gateway to activate')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )

    async def install_browser_guidance(self, row, data):
        """Keep owner notes and append the verified, general browser tool contract."""
        guidance = (self.root / "infra/morrow-browser-guidance.md").read_text()
        code = "\n".join(
            [
                "import os,time,shutil; from pathlib import Path",
                "root=Path('/sandbox/.openclaw'); workspace=root/'workspace'",
                "assert workspace.is_dir() and not workspace.is_symlink()",
                "p=workspace/'AGENTS.md'; assert not p.is_symlink()",
                "text=p.read_text() if p.exists() else ''; assert len(text)<=131072",
                "start='<!-- morrow-browser-guidance:start -->'",
                "end='<!-- morrow-browser-guidance:end -->'",
                f"block=start+'\\n'+{guidance!r}.strip()+'\\n'+end",
                "if start in text or end in text:",
                " assert text.count(start)==text.count(end)==1",
                " a=text.index(start); b=text.index(end); assert a<b",
                " retained=text[:a]+text[b+len(end):]",
                " result=block+'\\n\\n'+retained.strip()+'\\n'",
                "else: result=block+'\\n\\n'+text.strip()+'\\n'",
                "if result!=text:",
                " backup=root/'morrow-policy-backups'/('browser-guidance-'+str(time.time_ns()))",
                " backup.mkdir(parents=True,mode=0o700)",
                " if p.exists(): shutil.copy2(p,backup/'AGENTS.md')",
                " temporary=p.with_name('.AGENTS.morrow-new'); assert not temporary.is_symlink()",
                " temporary.write_text(result); os.chmod(temporary,0o600); os.replace(temporary,p)",
                "print('Managed browser guidance reconciled; existing owner notes retained')",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "998", data["Id"], "python3", "-c", code],
            str(row["id"]),
        )

    async def ensure_egress_policy(self, iid, row):
        name = row["sandbox_name"]
        try:
            out = await self.command(
                self.cli(iid, "policy", "get", name, "--base", "-o", "json"), iid
            )
            data = json.loads(out)
            policy = data.get("policy", {})
            net_policies = policy.setdefault("network_policies", {})
            rule_name = f"allow_host_openshell_internal_{self.settings.egress_proxy_port}"
            existing = net_policies.get(rule_name, {})
            endpoints = existing.get("endpoints", [])
            already_configured = (
                endpoints
                and endpoints[0].get("port") == self.settings.egress_proxy_port
                and endpoints[0].get("tls") == "skip"
                and endpoints[0].get("access") == "full"
            )
            if not already_configured:
                net_policies[rule_name] = {
                    "name": rule_name,
                    "endpoints": [
                        {
                            "host": "host.openshell.internal",
                            "port": self.settings.egress_proxy_port,
                            "access": "full",
                            "tls": "skip",
                        }
                    ],
                    "binaries": [
                        {"path": "/usr/lib/chromium/chromium"},
                        {"path": "/usr/local/bin/node"},
                        {"path": "/usr/bin/node"},
                        {"path": "/usr/bin/python3"},
                        {"path": "/usr/bin/python3.13"},
                    ],
                }
                policy_file = self.metadata / f"{iid}-egress-policy.json"
                policy_file.write_text(json.dumps(policy, indent=2))
                policy_file.chmod(0o600)
                await self.command(
                    self.cli(iid, "policy", "set", "--policy", str(policy_file), name, "--wait"),
                    iid,
                )
        except Exception as e:
            logger.warning("Failed to configure egress policy for %s: %s", name, e)
            raise RuntimeError("BROWSER_EGRESS_POLICY_FAILED") from e

    async def ensure_egress_bridge(self, row, data):
        """Start the fixed egress transport through supported tenant execution."""
        lock = self.browser_bridge_locks.setdefault(str(row["id"]), asyncio.Lock())
        async with lock:
            await self._ensure_egress_bridge(row, data)

    async def _ensure_egress_bridge(self, row, data):
        iid = str(row["id"])
        source = Path(__file__).parents[1] / "browser_bridge.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        temporary = f"/usr/local/bin/.morrow-egress-{iid}"
        target = "/usr/local/bin/morrow-egress-bridge.py"
        await self.command(["docker", "cp", str(source), f"{data['Id']}:{temporary}"], iid)
        code = "\n".join(
            [
                "import hashlib,os; from pathlib import Path",
                f"source=Path({temporary!r}); target=Path({target!r})",
                "assert not source.is_symlink() and not target.is_symlink()",
                f"assert hashlib.sha256(source.read_bytes()).hexdigest()=={digest!r}",
                "os.chown(source,0,0); os.chmod(source,0o755); os.replace(source,target)",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "0", data["Id"], "python3", "-c", code], iid
        )
        result = await self.command(
            self.cli(
                iid,
                "sandbox",
                "exec",
                "--name",
                row["sandbox_name"],
                "--",
                "python3",
                target,
                "--ensure",
                "--port",
                str(self.settings.egress_proxy_port),
            ),
            iid,
        )
        if result.strip() != "BROWSER_EGRESS_READY":
            raise RuntimeError("BROWSER_EGRESS_NOT_READY")

    async def prepare_automation_access(self, row):
        """Explicitly pair only this host-held scheduler key, never browser devices.

        Native cron writes require admin scope. It is not added to the automatic
        pairing policy or either chat/review identity. This operator/provisioning
        action is not callable through the frontend API.
        """
        from ..errors import APIError
        from ..gateway import GatewayClient

        self.bind(row)
        iid = str(row["id"])
        sandbox = await self.sandbox(row)
        if not sandbox or sandbox["phase"] != "Ready":
            raise RuntimeError("AUTOMATION_RUNTIME_NOT_READY")
        await self.inspect(row, sandbox)

        class MaintenanceGuard:
            async def run(self, operation):
                return await operation

        client = GatewayClient(
            SimpleNamespace(settings=self.settings),
            SimpleNamespace(user_id=row["owner_user_id"]),
            row,
            MaintenanceGuard(),
        )
        client.scopes = ["operator.admin"]
        identity = await client.device("scheduler-provisioning")
        try:
            await client.open()
            return
        except APIError:
            pass
        finally:
            await client.close()
        backup = self.state / "backups" / f"automation-access-{iid}-{uuid4().hex}"
        backup.mkdir(mode=0o700, parents=True)
        data = await self.inspect(row, sandbox)
        native_backup = f"/tmp/morrow-pairing-{uuid4().hex}.sqlite"
        backup_code = "\n".join(
            [
                "import sqlite3,os",
                "source=sqlite3.connect('file:/sandbox/.openclaw/state/"
                "openclaw.sqlite?mode=ro',uri=True)",
                f"target=sqlite3.connect({native_backup!r})",
                "source.backup(target); target.close(); source.close()",
                f"os.chmod({native_backup!r},0o600)",
            ]
        )
        await self.command(
            ["docker", "exec", "--user", "998", data["Id"], "python3", "-c", backup_code],
            iid,
        )
        try:
            await self.command(
                ["docker", "cp", f"{data['Id']}:{native_backup}", str(backup / "pairing.sqlite")],
                iid,
            )
        finally:
            await self.command(
                [
                    "docker",
                    "exec",
                    "--user",
                    "998",
                    data["Id"],
                    "python3",
                    "-c",
                    f"import os; os.unlink({native_backup!r})",
                ],
                iid,
            )
        for path in backup.rglob("*"):
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
        code = "\n".join(
            [
                "import fs from 'node:fs';",
                "import assert from 'node:assert/strict';",
                "const root='/sandbox/.openclaw';",
                f"const id={json.dumps(identity['id'])}, key={json.dumps(identity['publicKey'])};",
                "const directory='/usr/local/lib/node_modules/openclaw/dist';",
                "const readers=fs.readdirSync(directory).filter("
                "n=>/^device-pairing-[A-Za-z0-9_]+\\.js$/.test(n));",
                "assert.equal(readers.length,1);",
                "const {l:list}=await import(directory+'/'+readers[0]);",
                "const pending=(await list(root)).pending;",
                "const matches=pending.filter(p=>p.deviceId===id&&p.publicKey===key);",
                "assert.equal(matches.length,1); const request=matches[0];",
                "assert.equal(request.role,'operator');",
                "assert.deepEqual(request.scopes,['operator.admin']);",
                "assert.equal(request.clientId,'openclaw-control-ui');",
                "assert.equal(request.clientMode,'ui'); assert.equal(request.platform,'server');",
                f"assert.equal(request.remoteIp,{json.dumps(self.settings.proxy_client_address())});",
                "const modules=fs.readdirSync(directory).filter("
                "n=>/^device-pairing-approval-.*\\.js$/.test(n));",
                "assert.equal(modules.length,1);",
                "const {n:approve}=await import(directory+'/'+modules[0]);",
                "const result=await approve(request.requestId,"
                "{callerScopes:['operator.admin']},root);",
                "assert.equal(result?.status,'approved');",
                "assert.equal(result.device.deviceId,id);",
                "assert.deepEqual(result.device.approvedScopes,['operator.admin']);",
                "console.log('SCHEDULER_IDENTITY_APPROVED');",
            ]
        )
        await self.command(
            self.cli(
                iid,
                "sandbox",
                "exec",
                "--name",
                row["sandbox_name"],
                "--",
                "node",
                "--input-type=module",
                "-e",
                code,
            ),
            iid,
        )
        check = GatewayClient(
            SimpleNamespace(settings=self.settings),
            SimpleNamespace(user_id=row["owner_user_id"]),
            row,
            MaintenanceGuard(),
        )
        check.scopes = ["operator.admin"]
        try:
            await check.open()
        finally:
            await check.close()

    async def agent_port(self, row):
        iid = str(row["id"])
        if iid not in self.target_ports:
            code = (
                "import json; print(json.load(open('/sandbox/.openclaw/openclaw.json'))"
                "['gateway']['port'])"
            )
            output = await self.command(
                self.cli(
                    iid,
                    "sandbox",
                    "exec",
                    "--name",
                    row["sandbox_name"],
                    "--",
                    "python3",
                    "-c",
                    code,
                ),
                iid,
            )
            self.target_ports[iid] = int(output.strip())
        port = self.target_ports[iid]
        if not 1024 <= port <= 65535:
            raise RuntimeError("INVALID_AGENT_PORT")
        return port

    async def forward(self, row):
        iid = str(row["id"])
        lock = self.forward_locks.setdefault(iid, asyncio.Lock())
        async with lock:
            return await self._forward(row)

    async def _forward(self, row):
        iid, name = str(row["id"]), row["sandbox_name"]
        port = await self.agent_port(row)
        socket = self.sockets / f"{iid}.sock"
        if (
            iid in self.forwards
            and self.forwards[iid].returncode is None
            and socket.exists()
            and socket.stat().st_ino == self.forward_inodes.get(iid)
        ):
            return "unix:" + str(socket)
        previous = socket.stat().st_ino if socket.exists() else None
        if iid in self.forwards and self.forwards[iid].returncode is None:
            self.forwards[iid].terminate()
            await self.forwards[iid].wait()
        config = self.metadata / f"{iid}.ssh"
        config.write_text(await self.command(self.cli(iid, "sandbox", "ssh-config", name), iid))
        config.chmod(0o600)
        with (self.metadata / f"{iid}.ssh.log").open("ab") as log:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                "-F",
                str(config),
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "IdentityAgent=none",
                "-o",
                "StreamLocalBindUnlink=yes",
                "-L",
                f"{socket}:127.0.0.1:{port}",
                f"openshell-{name}.default",
                env=self.environment(iid),
                stdout=log,
                stderr=log,
            )
        self.forwards[iid] = proc
        for _ in range(50):
            if proc.returncode is not None:
                raise RuntimeError("PRIVATE_INGRESS_FAILED")
            if (
                socket.exists()
                and stat.S_ISSOCK(socket.stat().st_mode)
                and socket.stat().st_ino != previous
            ):
                self.forward_inodes[iid] = socket.stat().st_ino
                return "unix:" + str(socket)
            await asyncio.sleep(0.1)
        raise RuntimeError("PRIVATE_INGRESS_TIMEOUT")

    async def remove_tcp_forward(self, row):
        iid = str(row["id"])
        port = await self.agent_port(row)
        # NemoClaw starts foreground `forward service` children; the stock `forward stop`
        # registry does not own these. Stop only this UID's exact pinned CLI/gateway/name.
        pattern = (
            re.escape(str(self.binary))
            + r".* forward service "
            + re.escape(row["sandbox_name"])
            + r" "
        )
        pids = (
            await self.command(["pgrep", "-u", str(os.getuid()), "-f", pattern], iid, check=False)
        ).split()
        for value in pids:
            pid = int(value)
            command = (
                await self.command(["ps", "-p", str(pid), "-o", "args="], iid, check=False)
            ).strip()
            if not command.startswith(str(self.binary) + " "):
                raise RuntimeError("FORWARD_PROCESS_IDENTITY_CHANGED")
            args = shlex.split(command[len(str(self.binary)) + 1 :])
            if (
                args[args.index("--gateway") + 1] != self.gateway(iid)
                or args[args.index("service") + 1] != row["sandbox_name"]
                or args[args.index("--target-port") + 1] != str(port)
            ):
                raise RuntimeError("FORWARD_PROCESS_IDENTITY_CHANGED")
            # Re-read immediately before signalling to avoid acting on stale PID evidence.
            again = (
                await self.command(["ps", "-p", str(pid), "-o", "args="], iid, check=False)
            ).strip()
            if again == command:
                with suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM)

    async def provision(self, row):
        async with self.lock:
            iid = str(row["id"])
            if row["sandbox_name"] != f"co-{UUID(iid).hex[:16]}":
                raise RuntimeError("INVALID_INSTANCE_BINDING")
            sandbox = await self.sandbox(row)
            if not sandbox:
                await self.command(
                    [
                        "node",
                        str(self.source / "bin/nemoclaw.js"),
                        "onboard",
                        "--non-interactive",
                        "--name",
                        row["sandbox_name"],
                        "--no-gpu",
                        "--no-sandbox-gpu",
                        "--events=jsonl",
                    ],
                    iid,
                    timeout=600,
                    inference_credentials=True,
                )
                sandbox = await self.sandbox(row)
            if not sandbox or sandbox["phase"] != "Ready":
                raise RuntimeError("MANAGED_WORKLOAD_NOT_READY")
            data = await self.inspect(row, sandbox)
            limits = data["HostConfig"]
            memory = min(limits.get("Memory") or 2**31, 2**31)
            cpus = min(limits.get("NanoCpus") or 2_000_000_000, 2_000_000_000) / 1_000_000_000
            configured_pids = limits.get("PidsLimit") or 512
            pids = min(configured_pids, 512) if configured_pids > 0 else 512
            await self.command(
                [
                    "docker",
                    "update",
                    "--cpus",
                    str(cpus),
                    "--memory",
                    str(memory),
                    "--memory-swap",
                    str(memory),
                    "--pids-limit",
                    str(pids),
                    data["Id"],
                ],
                iid,
            )
            await self.patch_startup(row, data)
            await self.patch_browser_navigation(row, data)
            await self.configure_gateway(row)
            endpoint = await self.forward(row)
            await self.remove_tcp_forward(row)
            record = {
                "id": iid,
                "sandbox_name": row["sandbox_name"],
                "runtime_id": sandbox["id"],
                "container_name": data["Name"].lstrip("/"),
                "container_id": data["Id"],
                "image_digest": data["Image"],
                "volume_name": row["volume_name"],
                "upstream_url": endpoint,
                "owner_user_id": row["owner_user_id"],
                "gateway_port": self.bindings[iid],
                "startup_patch_sha256": self.manifest["startup_patched_sha256"],
                "browser_navigation_patch_sha256": self.manifest[
                    "browser_navigation_patched_sha256"
                ],
                "browser_snapshot_patch_sha256": self.manifest["browser_snapshot_patched_sha256"],
                "browser_playwright_patch_sha256": self.manifest[
                    "browser_playwright_patched_sha256"
                ],
                "browser_observation_patch_sha256": self.manifest[
                    "browser_observation_patched_sha256"
                ],
                "browser_catalog_patch_sha256": self.manifest["browser_catalog_patched_sha256"],
            }
            path = self.metadata / f"{iid}.json"
            path.write_text(json.dumps(record, indent=2))
            path.chmod(0o600)
            candidate = {**row, "runtime_id": sandbox["id"], "upstream_url": endpoint}
            # Native Ready means the supervisor/SSH is up. The assistant process
            # can still be starting after a legitimate native restart.
            for _ in range(12):
                if await self.probe(candidate):
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("ASSISTANT_STARTUP_TIMEOUT")
            await self.prepare_automation_access(candidate)
            await self.prepare_workspace_access(candidate)
            return RuntimeResult(sandbox["id"], endpoint, record["container_name"])

    async def probe(self, row):
        try:
            sandbox = await self.sandbox(row)
            if not sandbox or sandbox["phase"] != "Ready":
                return False
            data = await self.inspect(row, sandbox)
            endpoint = await self.forward(row)
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=endpoint.removeprefix("unix:")),
                trust_env=False,
                timeout=5,
            ) as client:
                if not (await client.get("http://openclaw.internal/healthz")).is_success:
                    return False
            await self.ensure_egress_bridge(row, data)
            return True
        except Exception:
            return False

    async def close(self):
        for proc in self.forwards.values():
            if proc.returncode is None:
                proc.terminate()
                with suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), 5)
