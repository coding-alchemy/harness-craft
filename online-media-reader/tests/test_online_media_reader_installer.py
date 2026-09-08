# -*- coding: utf-8 -*-
"""online-media-reader 安装器合同测试：薄参数化文件。

合同实现位于仓库级 tests/installer_contract.py；两个模块的 install_skill.py
按批准设计保持独立实现，安装合同只维护这一份。
"""

import sys
from pathlib import Path

import pytest

REPO_TESTS = Path(__file__).resolve().parents[2] / "tests"
sys.path.insert(0, str(REPO_TESTS))
import installer_contract  # noqa: E402

MODULE_ROOT = Path(__file__).resolve().parent.parent


def prepare_fixtures(source_copy, work_root):
    return None


def out_of_source(session, installed_skill, context):
    """删除安装来源后，两个入口必须从安装目录独立启动。"""
    for entry in ("read.py", "review.py"):
        result = session.run_python(
            str(installed_skill / "scripts" / entry), "--help"
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout


CONTRACT = installer_contract.InstallerContract(
    module_root=MODULE_ROOT,
    skill_name="online-media-reader",
    forbidden_top_dirs=("tests", "specs", "architecture"),
    prepare_fixtures=prepare_fixtures,
    out_of_source=out_of_source,
)


@pytest.mark.parametrize(
    "check", installer_contract.CHECKS, ids=lambda check: check.__name__
)
def test_installer_contract(check):
    check(CONTRACT)
