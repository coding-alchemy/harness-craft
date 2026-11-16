# -*- coding: utf-8 -*-
"""tech-doc-translator 安装器合同测试：薄参数化文件。

合同实现位于仓库级 tests/installer_contract.py；两个模块的 install_skill.py
按批准设计保持独立实现，安装合同只维护这一份。
"""

import json
import shutil
import subprocess
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
    generated_files=(".install-manifest.json",),
)


@pytest.mark.parametrize(
    "check", installer_contract.CHECKS, ids=lambda check: check.__name__
)
def test_installer_contract(check):
    check(CONTRACT)


def test_installed_copy_reports_modified_files_without_blocking():
    directory, session = installer_contract.make_session(CONTRACT)
    try:
        assert session.run().returncode == 0
        manifest = json.loads((session.target / ".install-manifest.json").read_text(encoding="utf-8"))
        assert set(manifest["files"]) == set(installer_contract.publish_files(CONTRACT.source_skill))
        script = str(session.target / "scripts" / "parse_api_html.py")
        clean = session.run_python(script, "--help")
        assert clean.returncode == 0 and "安装清单" not in clean.stderr, clean.stderr
        edited = session.target / "references" / "cleanup.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "\n本地改动\n", encoding="utf-8")
        (session.target / "references" / "numeric_review.md").unlink()
        warned = session.run_python(script, "--help")
        assert warned.returncode == 0 and "usage:" in warned.stdout
        assert "与安装清单不符" in warned.stderr
        assert "references/cleanup.md" in warned.stderr
        assert "references/numeric_review.md（缺失）" in warned.stderr
        assert session.run("--force").returncode == 0
        assert "安装清单" not in session.run_python(script, "--help").stderr
        (session.target / ".install-manifest.json").write_text("{", encoding="utf-8")
        broken = session.run_python(script, "--help")
        assert broken.returncode == 0 and "安装清单读不出" in broken.stderr
        (session.target / ".install-manifest.json").write_text('{"files": []}', encoding="utf-8")
        shaped = session.run_python(script, "--help")
        assert shaped.returncode == 0 and "安装清单读不出" in shaped.stderr, shaped.stderr
    finally:
        directory.cleanup()


def test_repository_checkout_has_no_manifest_and_no_warning():
    script = CONTRACT.source_skill / "scripts" / "parse_api_html.py"
    result = subprocess.run([sys.executable, str(script), "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "安装清单" not in result.stderr, result.stderr


def test_files_created_by_running_the_installed_copy_do_not_warn():
    """评审关注：运行安装副本会生成 __pycache__，项目也可能留下自己的文件；清单外的文件不触发提示。"""
    directory, session = installer_contract.make_session(CONTRACT)
    try:
        assert session.run().returncode == 0
        assert (session.target / ".install-manifest.json").is_file()
        cache = session.target / "scripts" / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "_verification.cpython-312.pyc").write_bytes(b"cache")
        (session.target / "notes.txt").write_text("项目自己的记录\n", encoding="utf-8")
        result = session.run_python(str(session.target / "scripts" / "parse_api_html.py"), "--help")
        assert result.returncode == 0 and "安装清单" not in result.stderr, result.stderr
    finally:
        directory.cleanup()
