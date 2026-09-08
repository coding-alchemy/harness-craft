# -*- coding: utf-8 -*-
"""tech-doc-translator 安装器合同测试：薄参数化文件。

合同实现位于仓库级 tests/installer_contract.py；两个模块的 install_skill.py
按批准设计保持独立实现，安装合同只维护这一份。
"""

import shutil
import sys
from pathlib import Path

import pytest

REPO_TESTS = Path(__file__).resolve().parents[2] / "tests"
sys.path.insert(0, str(REPO_TESTS))
import installer_contract  # noqa: E402

MODULE_ROOT = Path(__file__).resolve().parent.parent


def prepare_fixtures(source_copy, work_root):
    """在删除安装来源前，把无网络夹具复制到工作区外的临时目录。"""
    fixtures = source_copy / "tests" / "fixtures"
    work = work_root / "fixture-run"
    (work / "images").mkdir(parents=True)
    shutil.copy(fixtures / "sample_single_page.html", work / "sample.html")
    shutil.copy(fixtures / "sample_translated.md", work / "sample_translated.md")
    shutil.copy(
        fixtures / "valid_1x1.png",
        work / "images" / "thread_hierarchy.png",
    )
    return None


def out_of_source(session, installed_skill, context):
    """删除安装来源后，代表性解析、校验、术语脚本与参考资料仍可用。"""
    work = session.root / "fixture-run"
    parse = session.run_python(
        str(installed_skill / "scripts" / "parse_single_page_html.py"),
        str(work / "sample.html"),
        str(work / "source.md"),
    )
    assert parse.returncode == 0, parse.stderr
    assert (work / "source.md").is_file()
    verify = session.run_python(
        str(installed_skill / "scripts" / "verify_translation.py"),
        str(work / "sample_translated.md"),
        str(work / "source.md"),
        "1. Compute Kernel Basics",
        "1.1. Thread Hierarchy",
        "1.1.1. Memory Model",
    )
    assert verify.returncode == 0, verify.stderr
    glossary = session.run_python(
        str(installed_skill / "scripts" / "select_glossary.py"), "--help"
    )
    assert glossary.returncode == 0, glossary.stderr
    assert "usage:" in glossary.stdout
    assert (installed_skill / "references" / "translation_conventions.md").is_file()
    assert (installed_skill / "references" / "glossaries" / "nvidia.md").is_file()
    assert "../../" not in (installed_skill / "SKILL.md").read_text(encoding="utf-8")


CONTRACT = installer_contract.InstallerContract(
    module_root=MODULE_ROOT,
    skill_name="tech-doc-translator",
    forbidden_top_dirs=("tests", "specs", "docs"),
    prepare_fixtures=prepare_fixtures,
    out_of_source=out_of_source,
)


@pytest.mark.parametrize(
    "check", installer_contract.CHECKS, ids=lambda check: check.__name__
)
def test_installer_contract(check):
    check(CONTRACT)
