import unittest
from pathlib import Path


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.skill = (
            Path(__file__).resolve().parents[1]
            / "skills" / "feishu-notify" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_uses_bundled_entry_script(self):
        self.assertIn("scripts/feishu_notify.py", self.skill)

    def test_documents_fixed_stdin_fallback(self):
        self.assertIn("stdin", self.skill)
        self.assertIn('"flow": "send"', self.skill)
        self.assertIn('"flow": "task-auto"', self.skill)

    def test_prohibits_shell_interpolation_and_sensitive_context(self):
        self.assertIn("不得", self.skill)
        self.assertIn("完整日志", self.skill)
        self.assertIn("内部推理", self.skill)

    def test_notification_failure_does_not_change_task_result(self):
        self.assertIn("不得改变原任务结果", self.skill)
