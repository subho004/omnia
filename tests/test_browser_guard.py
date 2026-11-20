import subprocess
from pathlib import Path


def test_browser_destination_hook_contract():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["node", "--test", str(root / "tests/browser-guard.test.mjs")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
