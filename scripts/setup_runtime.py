"""Install the pinned local runtime toolchain without changing global installations.

Activation permits real provisioning. It does not declare an existing sandbox healthy;
each job must still pass runtime, mount, ownership, and private-ingress checks.
"""

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

import httpx

from claw_orchestrator.config import Settings
from claw_orchestrator.inference import openrouter_preflight

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state"


def run(*args, cwd=ROOT, check=True):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("The verified runtime toolchain currently targets macOS Apple Silicon.")
    for command in ("docker", "node", "npm", "git", "ssh"):
        if not shutil.which(command):
            raise SystemExit(f"Required tool is missing: {command}")
    manifest = json.loads((ROOT / "infra/runtime-versions.json").read_text())
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    downloads, binaries = STATE / "downloads", STATE / "bin"
    downloads.mkdir(exist_ok=True)
    binaries.mkdir(exist_ok=True)
    for binary, hash_key in (
        ("openshell", "openshell_darwin_arm64_sha256"),
        ("openshell-gateway", "openshell_gateway_darwin_arm64_sha256"),
    ):
        name = f"{binary}-aarch64-apple-darwin.tar.gz"
        archive = downloads / name
        if not archive.exists():
            url = (
                "https://github.com/NVIDIA/OpenShell/releases/download/v"
                + manifest["openshell_version"]
                + "/"
                + name
            )
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
                shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest[hash_key]:
            raise SystemExit(f"Archive checksum mismatch: {name}. Kept it for inspection.")
        with tarfile.open(archive) as source:
            members = source.getmembers()
            if len(members) != 1 or members[0].name != binary or not members[0].isfile():
                raise SystemExit(f"Unexpected archive layout: {name}")
            source.extractall(binaries, filter="data")
        (binaries / binary).chmod(0o755)
    source = STATE / "research/nemoclaw"
    if not source.exists():
        source.parent.mkdir(exist_ok=True)
        run(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            manifest["nemoclaw_tag"],
            "https://github.com/NVIDIA/NemoClaw.git",
            str(source),
        )
    revision = run("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
    if revision != manifest["nemoclaw_source_revision"]:
        raise SystemExit(
            "Existing runtime source has a different revision; it was not overwritten."
        )
    for relative in [manifest["local_patch"], *manifest.get("additional_patches", [])]:
        patch = str(ROOT / relative)
        if run("git", "apply", "--reverse", "--check", patch, cwd=source, check=False).returncode:
            run("git", "apply", "--check", patch, cwd=source)
            run("git", "apply", patch, cwd=source)
    print("Building pinned NemoClaw with the reviewed local compatibility patches…", flush=True)
    run("node", "scripts/lib/openshell-sdk-install.mts", "prepare", cwd=source)
    run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", cwd=source)
    run("node", "scripts/lib/openshell-sdk-install.mts", "check", cwd=source)
    run("npm", "run", "build:cli", cwd=source)
    if args.activate:
        settings = Settings()
        if settings.inference_provider == "openrouter":

            async def check_openrouter():
                async with httpx.AsyncClient(
                    timeout=30, follow_redirects=False, trust_env=False
                ) as client:
                    return await openrouter_preflight(settings, client)

            try:
                asyncio.run(check_openrouter())
            except Exception:
                raise SystemExit(
                    "OpenRouter preflight failed; details omitted to protect credentials."
                ) from None
        else:
            endpoint = manifest["inference_endpoint"].rstrip("/") + "/models"
            with urllib.request.urlopen(endpoint, timeout=5) as response:
                models = json.load(response)
            if manifest["inference_model"] not in {m["id"] for m in models["data"]}:
                raise SystemExit("The configured LM Studio model is not available.")
        ready = STATE / "runtime-ready.json"
        ready.write_text(json.dumps({"source_revision": revision}))
        ready.chmod(0o600)
        print(
            "Managed provisioning enabled. Restart the API; each instance is verified individually."
        )
    else:
        print(
            "Toolchain prepared. Use --activate when the selected inference provider is available."
        )


if __name__ == "__main__":
    main()
