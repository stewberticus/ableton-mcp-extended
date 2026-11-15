"""docs/TOOLS.md must list exactly the tools the server registers."""
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_tools_doc_is_up_to_date():
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "gen_tools_doc.py"), "--check"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
