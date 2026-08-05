import unittest
from pathlib import Path


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "feishu-notify"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_has_expected_frontmatter_name(self):
        self.assertIn("name: feishu-notify", self.skill)

    def test_explicit_send_uses_send_subcommand(self):
        self.assertIn("feishu_notify.py send --message", self.skill)

    def test_requires_literal_argv_for_dynamic_values_without_shell_evaluation(self):
        self.assertIn("independent, literal argv parameter", self.skill)
        self.assertIn("must not be handed to shell parsing", self.skill)
        self.assertIn("shell execution disabled", self.skill)
        self.assertNotIn('--message "<user-designated text>"', self.skill)
        self.assertNotIn('--task "<task>"', self.skill)

    def test_documents_shell_only_safe_fallback_adapter(self):
        self.assertIn("## Shell-only execution fallback", self.skill)
        fallback = self.skill.split("## Shell-only execution fallback", 1)[1]
        for required in (
            "feishu_notify_adapter.py",
            "separate stdin/input-data channel",
            "feishu_notify.py send --message",
            "feishu_notify.py task --auto",
            "cannot provide separate stdin data",
        ):
            self.assertIn(required, fallback)
        self.assertNotIn("temporary JSON file", fallback)
        self.assertNotIn("python3 -c", fallback)

    def test_automatic_send_uses_task_auto_gate(self):
        self.assertIn("feishu_notify.py task --auto", self.skill)

    def test_requires_all_five_task_fields(self):
        for argument in ("--status", "--task", "--summary", "--repo", "--branch"):
            self.assertIn(argument, self.skill)

    def test_prohibits_full_results_logs_diffs_and_reasoning(self):
        for phrase in ("完整最终回复", "完整日志", "Diff", "内部推理"):
            self.assertIn(phrase, self.skill)

    def test_notification_failure_preserves_original_task_result(self):
        self.assertIn("不得改变原任务结果", self.skill)


class ReadmeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (
            Path(__file__).resolve().parents[1] / "README.md"
        ).read_text(encoding="utf-8")

    def test_documents_feishu_admin_prerequisites(self):
        for phrase in ("企业自建应用", "机器人能力", "im:message:send_as_bot", "可用范围"):
            self.assertIn(phrase, self.readme)

    def test_documents_configuration_and_both_commands(self):
        for phrase in (
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_RECEIVE_OPEN_ID",
            "FEISHU_AUTO_NOTIFY",
            "feishu_notify.py send",
            "feishu_notify.py task",
        ):
            self.assertIn(phrase, self.readme)

    def test_documents_failure_isolation_and_offline_tests(self):
        self.assertIn("不会改变原任务结果", self.readme)
        self.assertIn("不访问真实飞书", self.readme)

    def test_marks_json_configuration_as_phase_two(self):
        self.assertIn("二期", self.readme)
        self.assertIn("config.json", self.readme)
        self.assertIn("一期不读取", self.readme)


if __name__ == "__main__":
    unittest.main()
