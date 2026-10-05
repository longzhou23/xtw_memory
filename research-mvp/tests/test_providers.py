"""Synthetic Codex process tests; never invoke a CLI or access replay data."""
import json
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from research_memory.contracts import Invalid
from research_memory.providers import CodexProvider


class CodexProviderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="provider-test-", dir="/tmp/opencode")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.env = {"XTW_RESEARCH_TMP": str(self.root)}
        self.addCleanup(patch.stopall)
        patch("research_memory.providers.os.environ", self.env).start()
        self.popen = patch("research_memory.providers.subprocess.Popen").start()
        self.killpg = patch("research_memory.providers.os.killpg").start()
        self.clock = patch("research_memory.providers.time.perf_counter", side_effect=[10.0, 11.23456]).start()
        self.process = Mock(pid=12345, returncode=0)
        self.process.communicate.return_value = ("", "")
        self.popen.side_effect = self.launch
        self.schema = {"type": "object", "properties": {"text": {"type": "string"}}}
        self.payload = {"text": "合成输入"}
        self.draft = {"text": "合成输出"}
        self.output_text = json.dumps(self.draft, ensure_ascii=False)
        self.write_output = True
        self.command = None

    def launch(self, command, **kwargs):
        self.command = command
        self.folder = Path(kwargs["cwd"])
        self.schema_path = Path(command[command.index("--output-schema") + 1])
        self.output_path = Path(command[command.index("--output-last-message") + 1])
        self.assertEqual(self.folder.parent, self.root)
        self.assertEqual(self.schema_path.parent, self.folder)
        self.assertEqual(self.output_path.parent, self.folder)
        self.assertEqual(json.loads(self.schema_path.read_text()), self.schema)
        if self.write_output:
            self.output_path.write_text(self.output_text)
        return self.process

    def generate(self):
        return CodexProvider().generate("Synthetic system", self.payload, self.schema)

    def test_success_returns_json_and_metadata(self):
        usage = {"input_tokens": 12, "output_tokens": 3}
        self.process.communicate.return_value = (
            "non-JSON CLI diagnostic\n" + json.dumps({"type": "turn.completed", "usage": usage}), ""
        )
        draft, metadata = self.generate()
        self.assertEqual(draft, self.draft)
        self.assertEqual(metadata, {
            "provider": "codex-configured-default",
            "model": "configured default; CLI may not expose model id",
            "modelProvider": "configured default", "transportRetries": None,
            "seconds": 1.235,
            "usage": [usage],
        })
        self.process.communicate.assert_called_once_with(
            "Synthetic system\nINPUT JSON:\n" + json.dumps(self.payload, ensure_ascii=False), timeout=240
        )
        self.killpg.assert_not_called()
        self.assertFalse(self.folder.exists())

    def test_command_disables_shell_and_web_and_uses_read_only_sandbox(self):
        self.generate()
        self.assertEqual(self.command, [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
            "--json", "--color", "never", "-c", "features.shell_tool=false", "-c", 'web_search="disabled"',
            "--output-schema", str(self.schema_path), "--output-last-message", str(self.output_path), "-",
        ])
        self.assertEqual(self.popen.call_args.kwargs, {
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "text": True, "cwd": self.folder, "start_new_session": True,
        })

    def test_configured_900_second_timeout_is_forwarded(self):
        self.env["XTW_RESEARCH_MODEL_TIMEOUT"] = "900"
        self.generate()
        self.assertEqual(self.process.communicate.call_args.kwargs, {"timeout": 900})

    def test_timeout_kills_child_group_drains_process_and_raises_invalid(self):
        self.env["XTW_RESEARCH_MODEL_TIMEOUT"] = "900"
        timeout = subprocess.TimeoutExpired("synthetic-codex", 900)
        self.process.communicate.side_effect = [timeout, ("", "")]
        sequence = Mock()
        sequence.attach_mock(self.process.communicate, "communicate")
        sequence.attach_mock(self.killpg, "killpg")
        with self.assertRaisesRegex(Invalid, "超过900秒") as caught:
            self.generate()
        self.assertIs(caught.exception.__cause__, timeout)
        self.assertEqual(sequence.mock_calls, [
            call.communicate("Synthetic system\nINPUT JSON:\n" + json.dumps(self.payload, ensure_ascii=False), timeout=900),
            call.killpg(self.process.pid, signal.SIGKILL),
            call.communicate(),
        ])
        self.assertFalse(self.folder.exists())

    def test_launch_oserror_becomes_invalid(self):
        error = OSError("synthetic launch failure")
        self.popen.side_effect = error
        with self.assertRaisesRegex(Invalid, "可执行程序不可用") as caught:
            self.generate()
        self.assertIs(caught.exception.__cause__, error)
        self.process.communicate.assert_not_called()
        self.killpg.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_exit_one_without_output_is_invalid(self):
        self.process.returncode = 1
        self.write_output = False
        with self.assertRaisesRegex(Invalid, r"exit=1"):
            self.generate()
        self.killpg.assert_not_called()

    def test_zero_exit_without_output_is_invalid(self):
        self.write_output = False
        with self.assertRaisesRegex(Invalid, r"exit=0"):
            self.generate()

    def test_invalid_output_json_is_rejected(self):
        self.output_text = "{not JSON"
        with self.assertRaisesRegex(Invalid, "输出不是JSON") as caught:
            self.generate()
        self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)

    def test_forbidden_tool_events_are_rejected(self):
        for tool in ("command_execution", "mcp_tool_call", "web_search", "file_change"):
            with self.subTest(tool=tool):
                self.clock.side_effect = [10.0]
                self.process.communicate.return_value = (
                    json.dumps({"type": "item.completed", "item": {"type": tool}}), ""
                )
                with self.assertRaisesRegex(Invalid, "工具.*拒绝提交"):
                    self.generate()

    def test_timeout_range_includes_10_and_1800(self):
        for seconds in (10, 1800):
            with self.subTest(seconds=seconds):
                self.clock.side_effect = [10.0, 11.0]
                self.env["XTW_RESEARCH_MODEL_TIMEOUT"] = str(seconds)
                self.generate()
                self.assertEqual(self.process.communicate.call_args.kwargs, {"timeout": seconds})

    def test_timeout_outside_allowed_range_is_rejected_before_launch(self):
        for seconds in (-1, 0, 9, 1801):
            with self.subTest(seconds=seconds):
                self.clock.side_effect = [10.0]
                self.env["XTW_RESEARCH_MODEL_TIMEOUT"] = str(seconds)
                with self.assertRaisesRegex(Invalid, "10–1800"):
                    self.generate()
                self.popen.assert_not_called()
                self.killpg.assert_not_called()
                self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
