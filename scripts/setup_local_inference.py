"""Operator-only local LM Studio route setup; no credentials are placed in tenant data."""

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path

from claw_orchestrator.config import Settings
from claw_orchestrator.db import Database
from claw_orchestrator.runtime.nemoclaw import NemoClawRuntime


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", choices=("user1", "user2"), help="Configure only this owner")
    args = parser.parse_args()
    s = Settings()
    if s.inference_provider != "lmstudio" or not s.lmstudio_api_key:
        raise RuntimeError(
            "Select LM Studio and provide LMSTUDIO_API_KEY in the private environment"
        )
    db = Database(s.database_url)
    await db.open()
    rt = NemoClawRuntime(s)
    backup = Path(".state/backups") / ("local-route-" + str(time.time_ns()))
    backup.mkdir(mode=0o700, parents=True)
    async with db.connection() as c:
        rows = await c.fetch(
            "SELECT * FROM instances WHERE ($1::text IS NULL OR owner_user_id=$1) "
            "ORDER BY owner_user_id",
            args.user,
        )
    for row in rows:
        iid = str(row["id"])
        rt.bind(row)
        state = Path(rt.environment(iid)["NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR"])
        a = sqlite3.connect(str(state / "openshell.db"))
        b = sqlite3.connect(str(backup / (row["owner_user_id"] + ".db")))
        a.backup(b)
        b.close()
        a.close()
        (backup / (row["owner_user_id"] + ".db")).chmod(0o600)
        env = rt.environment(iid)
        env["LMSTUDIO_API_KEY"] = s.lmstudio_api_key.get_secret_value()

        async def cli(*args, _iid=iid, _env=env, _allow_missing=False):
            proc = await asyncio.create_subprocess_exec(
                *rt.cli(_iid, *args),
                env=_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, error = await proc.communicate()
            if proc.returncode:
                if _allow_missing and "not found" in error.decode():
                    return None
                safe = error.decode().replace(s.lmstudio_api_key.get_secret_value(), "[REDACTED]")
                raise RuntimeError("Native local provider operation failed: " + safe[-400:])
            return output.decode()

        profile = "morrow-lmstudio-local-v1"
        provider_name = "morrow-lmstudio-" + row["owner_user_id"]
        exported = await cli(
            "provider", "profile", "export", profile, "-o", "json", _allow_missing=True
        )
        if exported:
            expected = json.loads(
                await asyncio.to_thread(Path("infra/lmstudio-provider.json").read_text)
            )

            def matches(actual, wanted):
                if isinstance(wanted, dict):
                    return isinstance(actual, dict) and all(
                        key in actual and matches(actual[key], value)
                        for key, value in wanted.items()
                    )
                if isinstance(wanted, list):
                    return (
                        isinstance(actual, list)
                        and len(actual) == len(wanted)
                        and all(any(matches(item, value) for item in actual) for value in wanted)
                    )
                return actual == wanted

            if not matches(json.loads(exported), expected):
                raise RuntimeError("Existing local inference profile has a different boundary")
        else:
            await cli("provider", "profile", "import", "--file", "infra/lmstudio-provider.json")
        providers_metadata = json.loads(await cli("provider", "list", "-o", "json"))
        existing = next(
            (item for item in providers_metadata if item["name"] == provider_name), None
        )
        if existing and existing["type"] != profile:
            raise RuntimeError("Existing local provider has a different endpoint boundary")
        if existing:
            await cli("provider", "update", provider_name, "--credential", "LMSTUDIO_API_KEY")
        else:
            await cli(
                "provider",
                "create",
                "--name",
                provider_name,
                "--type",
                profile,
                "--credential",
                "LMSTUDIO_API_KEY",
            )
        await cli("sandbox", "provider", "attach", row["sandbox_name"], provider_name)
        # The supervisor applies provider bindings asynchronously. Wait for a
        # scoped reference before saving the model route; never store a raw key.
        handle_probe = (
            "import os,re; print(bool(re.fullmatch("
            "r'openshell:resolve:env:(v[0-9]{1,20}|s[a-f0-9]{64})_LMSTUDIO_API_KEY',"
            "os.environ.get('LMSTUDIO_API_KEY',''))))"
        )
        for _ in range(20):
            ready = await cli(
                "sandbox", "exec", "--name", row["sandbox_name"],
                "--", "python3", "-c", handle_probe,
            )
            if ready.strip() == "True":
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError("Scoped local provider binding did not become ready")
        model = {"primary": "inference/" + rt.manifest["inference_model"], "fallbacks": []}
        providers = {
            "inference": {
                "baseUrl": "http://host.openshell.internal:1234/v1",
                "apiKey": "openshell:resolve:env:LMSTUDIO_API_KEY",
                "api": "openai-completions",
                "timeoutSeconds": rt.manifest.get("inference_request_timeout_seconds", 600),
                "models": [
                    {
                        "id": rt.manifest["inference_model"],
                        "name": "Local assistant",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": rt.manifest["inference_context_window"],
                        "maxTokens": rt.manifest["inference_max_tokens"],
                    }
                ],
            }
        }
        # A restored native profile can override the provider's inline key.
        # Rebind only its default local profile through the native transaction
        # API, preserving other providers and keeping real credentials on host.
        profile_code = "\n".join(
            [
                "import fs from 'node:fs'; import assert from 'node:assert/strict';",
                "const root='/sandbox/.openclaw', agentDir=root+'/agents/main/agent';",
                "const handle=process.env.LMSTUDIO_API_KEY ?? '';",
                "assert.match(handle,/^openshell:resolve:env:"
                "(v[0-9]{1,20}|s[a-f0-9]{64})_LMSTUDIO_API_KEY$/);",
                "const directory='/usr/local/lib/node_modules/openclaw/dist';",
                "let sdk; for (const name of fs.readdirSync(directory).filter("
                "n=>/^auth-profiles-.*\\.js$/.test(n))) {",
                " const candidate=await import(directory+'/'+name);",
                " if (candidate.ensureAuthProfileStore && "
                "candidate.upsertAuthProfileWithLockOrThrow) {",
                "  assert.equal(sdk,undefined); sdk=candidate; } }",
                "assert.ok(sdk); const store=sdk.ensureAuthProfileStore(agentDir);",
                "const profileId='inference:default', credential=store.profiles[profileId];",
                "if (credential) {",
                " assert.equal(credential.provider,'inference');",
                " assert.equal(credential.type,'api_key');",
                " const backup=root+'/morrow-provider-backups';",
                " fs.mkdirSync(backup,{recursive:true,mode:0o700});",
                " fs.writeFileSync(backup+'/profile-'+Date.now()+'.json',"
                "JSON.stringify({[profileId]:credential}),{mode:0o600});",
                " await sdk.upsertAuthProfileWithLockOrThrow({profileId,"
                "credential:{...credential,key:undefined,keyRef:{source:'env',provider:'default',"
                "id:'LMSTUDIO_API_KEY'}},agentDir,stateDir:root});",
                " await sdk.clearAuthProfileCooldown({store:sdk.ensureAuthProfileStore(agentDir),"
                "profileId,agentDir});",
                " assert.equal(sdk.ensureAuthProfileStore(agentDir)"
                ".profiles[profileId].keyRef.id,'LMSTUDIO_API_KEY');",
                "}",
                "console.log('Local inference profile reconciled');",
            ]
        )
        await cli(
            "sandbox", "exec", "--name", row["sandbox_name"],
            "--", "node", "--input-type=module", "-e", profile_code,
        )
        code = "\n".join(
            [
                "import json,os,shutil,time,re",
                "from pathlib import Path",
                "p='/sandbox/.openclaw/openclaw.json'",
                "shutil.copy2(p,p+'.before-local-'+str(time.time_ns()))",
                "c=json.load(open(p))",
                "c.setdefault('tools',{})['toolSearch']={'enabled':True,'mode':'tools',"
                "'searchDefaultLimit':2}",
                "previous=c.get('models',{}).get('providers',{}).get('inference',{})",
                "providers=" + repr(providers),
                "selected=providers['inference']; ids={m['id'] for m in selected['models']}",
                "if (previous.get('baseUrl')==selected['baseUrl'] "
                "and previous.get('api')==selected['api']):",
                " for old_model in previous.get('models',[]):",
                "  if old_model.get('id') not in ids: "
                "selected['models'].append(old_model); ids.add(old_model.get('id'))",
                "c.setdefault('models',{})['providers']=providers",
                "handle=os.environ.get('LMSTUDIO_API_KEY','')",
                "assert re.fullmatch(r'openshell:resolve:env:'"
                "r'(v[0-9]{1,20}|s[a-f0-9]{64})_LMSTUDIO_API_KEY',handle), "
                "'Scoped local provider handle unavailable'",
                "c['models']['providers']['inference']['apiKey']="
                "{'source':'env','provider':'default','id':'LMSTUDIO_API_KEY'}",
                "a=c.setdefault('agents',{}); a.setdefault('defaults',{})['model']=" + repr(model),
                "a['defaults']['modelSelectionScope']='session'",
                "a['defaults']['thinkingDefault']="
                + repr(rt.manifest.get("inference_thinking_level", "off")),
                "a['defaults'].setdefault('models',{}).setdefault(" + repr(model['primary'])
                + ",{}).setdefault('params',{}).update(" + repr(rt.local_inference_params()) + ")",
                "for entry in a.get('entries',{}).values():\n if 'model' in entry: entry['model']="
                + repr(model),
                "owner=os.stat('/sandbox/.openclaw')",
                "with open(p+'.local','w') as f:json.dump(c,f)",
                "os.chmod(p+'.local',0o600);os.chown(p+'.local',owner.st_uid,owner.st_gid)",
                "os.replace(p+'.local',p)",
                "print('Native local model configured')",
            ]
        )
        await rt.command(
            rt.cli(
                iid, "sandbox", "exec", "--name", row["sandbox_name"], "--", "python3", "-c", code
            ),
            iid,
        )
        # The scoped credential namespace can change on every native start.
        # Resolve its environment reference at startup rather than persisting a
        # previous namespace. Use the supported lifecycle, preserving identity.
        await rt.command(rt.cli(iid, "sandbox", "stop", row["sandbox_name"]), iid)
        for _ in range(60):
            if (await rt.sandbox(row))["phase"] == "Stopped":
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Native local route stop did not complete")
        await rt.command(rt.cli(iid, "sandbox", "start", row["sandbox_name"]), iid)
        for _ in range(60):
            sandbox = await rt.sandbox(row)
            if sandbox["phase"] == "Ready":
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Native local route start did not complete")
        if sandbox["id"] != row["runtime_id"]:
            raise RuntimeError("Native identity changed during local route restart")
        data = await rt.inspect(row, sandbox)
        await rt.ensure_egress_bridge(row, data)
        print(
            row["owner_user_id"] + ": local model route and "
            + str(rt.manifest["inference_context_window"]) + " context configured", flush=True
        )
    await db.close()


asyncio.run(main())
