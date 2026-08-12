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

    def test_documents_card_task_contract_and_safety_rules(self):
        for required in (
            "--project", "--conversation", "--content", '"project"',
            '"conversation"', '"content"', "手动取消", "最多执行一次",
            "用户可见原因", "完整日志", "内部推理", "消息卡片",
            "success", "failure", "confirm",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.skill)
        for removed in ("--task", "--summary", "--repo", "--branch", "--source"):
            self.assertNotIn(removed, self.skill)

    def test_documents_cover_shared_interface_and_confirmation_trigger(self):
        frontmatter = self.skill.split("---", 2)[1]
        self.assertIn("任务结果或待确认节点", frontmatter)
        for document in (
            Path(__file__).resolve().parents[1] / "README.md",
            Path(__file__).resolve().parents[1] / "docs" / "USAGE.md",
            Path(__file__).resolve().parents[1] / "specs" / "feishu-connector.md",
        ):
            with self.subTest(document=document):
                self.assertIn(
                    "Codex 与 OpenCode 共用相同的 argv/stdin 显式接口",
                    document.read_text(encoding="utf-8"),
                )

    def test_documents_cover_project_configuration_selection_order(self):
        for document in (
            Path(__file__).resolve().parents[1] / "README.md",
            Path(__file__).resolve().parents[1] / "docs" / "USAGE.md",
            Path(__file__).resolve().parents[1] / "specs" / "feishu-connector.md",
        ):
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document):
                self.assertIn("`--project-root` 是全局选项", text)
                self.assertIn("显式路径、Git 项目根目录、当前工作目录", text)
