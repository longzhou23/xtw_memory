import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]

class DistributionTests(unittest.TestCase):
    def test_client_help_without_weights_or_virtualenv(self):
        result = subprocess.run([str(ROOT / "scripts/chat-gateway"), "--help"], cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("serve", result.stdout)

    def test_serve_requires_explicit_seal(self):
        env = dict(os.environ)
        env.pop("XTW_MEMORY_SEAL", None)
        result = subprocess.run([str(ROOT / "scripts/chat-gateway"), "serve", "--writer", "codex"], cwd="/tmp", env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--seal", result.stderr)
        self.assertFalse((ROOT / "research-mvp/var").exists())

    def test_no_private_or_generated_files_in_snapshot(self):
        forbidden = {".sqlite3", ".db", ".safetensors", ".pt", ".bin", ".jsonl", ".token"}
        for path in ROOT.rglob("*"):
            if any(part in {".git", "__pycache__"} for part in path.parts):
                continue
            if path.is_file():
                self.assertNotIn(path.suffix, forbidden, str(path))
