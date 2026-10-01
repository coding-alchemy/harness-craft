"""临时产物告警的固定语义验收（迁移 A：四类解析 CLI 落盘提醒）。"""
import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'))
from _html_fidelity import temp_root_paths, warn_if_temp_output  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'
FIXTURES = Path(__file__).parent / 'fixtures'


class TempRootPathsTest(unittest.TestCase):

    def test_roots_cover_current_tempdir_as_realpath(self):
        roots = temp_root_paths()
        self.assertIn(os.path.realpath(tempfile.gettempdir()), roots)
        for root in roots:
            self.assertEqual(root, os.path.realpath(root))


class WarnIfTempOutputTest(unittest.TestCase):

    def run_warning(self, paths):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            hit = warn_if_temp_output(paths)
        return hit, stderr.getvalue()

    def test_temp_path_warns_with_both_spellings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'sample_source.md')
            hit, err = self.run_warning([out])
            self.assertTrue(hit)
            self.assertIn('警告: 以下产物位于系统临时目录', err)
            self.assertIn(out, err)
            self.assertIn(os.path.realpath(out), err)

    def test_symlink_alias_warns_after_resolution(self):
        # /tmp 在 macOS 上是 /private/tmp 的符号链接别名：传入别名拼写，
        # 判定必须基于解析后的真实路径，而不是字符串前缀。
        alias = '/tmp/techdoc-alias-probe.md'
        hit, err = self.run_warning([alias])
        self.assertTrue(hit)
        self.assertIn(alias, err)
        self.assertIn(os.path.realpath(alias), err)

    def test_normal_and_lookalike_paths_do_not_warn(self):
        lookalike = '/var/tmp-similar/out.md'
        normal = os.path.join(os.path.expanduser('~'), 'work', 'out.md')
        if any(os.path.realpath(normal) == root
               or os.path.realpath(normal).startswith(root + os.sep)
               for root in temp_root_paths()):
            self.skipTest('HOME 位于临时根内，无法构造普通路径')
        hit, err = self.run_warning([lookalike, normal])
        self.assertFalse(hit)
        self.assertEqual(err, '')

    def test_empty_entries_skipped_and_no_exit(self):
        hit, err = self.run_warning(['', None])
        self.assertFalse(hit)
        self.assertEqual(err, '')


class ParseCliTempWarningTest(unittest.TestCase):
    """四类解析 CLI 的真实调用：正常退出、stderr 告警、正文与映射不变。"""

    CASES = {
        'parse_single_page_html': ('sample_single_page.html', 'single_source.md'),
        'parse_reference_html': ('math_reference.html', 'math_source.md'),
        'parse_api_html': (Path('multipage_site/api_page1.html').as_posix(),
                           'api_page1.md'),
    }

    def run_cli(self, module, argv):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / (module + '.py')), *argv],
            capture_output=True, text=True)

    def invoke_main(self, module, argv):
        real_argv, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cli = importlib.import_module(module)
                cli.main()
        finally:
            sys.argv = real_argv

    def test_real_parse_exits_zero_with_stderr_warning(self):
        for module, (fixture, out_name) in self.CASES.items():
            with self.subTest(module=module):
                with tempfile.TemporaryDirectory() as tmp:
                    out = os.path.join(tmp, out_name)
                    done = self.run_cli(
                        module, [str(FIXTURES / fixture), out])
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertIn('警告: 以下产物位于系统临时目录',
                                  done.stderr)
                    self.assertNotIn('警告', done.stdout)
                    body = Path(out).read_text(encoding='utf-8')
                    self.assertTrue(body.strip(), '解析正文为空')
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'paginated_page1.html'
            src.write_bytes((FIXTURES / 'paginated_page1.html').read_bytes())
            done = self.run_cli('parse_paginated_html', [str(src)])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('警告: 以下产物位于系统临时目录', done.stderr)
            out = src.with_suffix('.md')
            self.assertTrue(out.read_text(encoding='utf-8').strip())

    def test_warning_does_not_change_generated_outputs(self):
        # 对四类 CLI 各做两次进程内运行：第一次真实告警，第二次把告警
        # 替换为记录桩。正文与显示映射必须逐字节一致（告警只提醒，
        # 不改变产物），且桩按 [out_path, display_map] 接入一次。
        # 分页家族是单输入参数形态，不并入供双参数调用共用的 CASES，
        # 仅在本用例的遍历源中补充，使下方分页分支实际执行。
        cases = dict(self.CASES)
        cases['parse_paginated_html'] = ('paginated_page1.html',
                                         'paginated_page1.md')
        for module, (fixture, out_name) in cases.items():
            with self.subTest(module=module):
                cli = importlib.import_module(module)
                with tempfile.TemporaryDirectory() as tmp:
                    if module == 'parse_paginated_html':
                        # 分页家族单输入参数、输出在输入旁：显示映射内嵌
                        # 输入快照路径，跨目录比较会因路径失真，改为同一
                        # 目录先后两次运行（真实告警→记录桩）后对比快照。
                        run_dir = Path(tmp) / 'paged'
                        run_dir.mkdir()
                        (run_dir / 'paginated_page1.html').write_bytes(
                            (FIXTURES / 'paginated_page1.html').read_bytes())
                        out_path = (run_dir / 'paginated_page1.html').with_suffix('.md')
                        argv = [str(SCRIPTS / (module + '.py')),
                                str(run_dir / 'paginated_page1.html')]
                    else:
                        run_dir = Path(tmp) / 'dual'
                        run_dir.mkdir()
                        out_path = run_dir / out_name
                        argv = [str(SCRIPTS / (module + '.py')),
                                str(FIXTURES / fixture), str(out_path)]
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.invoke_main(module, argv)
                    loud_body = out_path.read_bytes()
                    loud_map = out_path.with_suffix('.images_display.json')
                    loud_map_body = (loud_map.read_bytes()
                                     if loud_map.exists() else None)
                    calls = []
                    original = cli.warn_if_temp_output
                    cli.warn_if_temp_output = (
                        lambda paths: calls.append(list(paths)) or False)
                    try:
                        self.invoke_main(module, argv)
                    finally:
                        cli.warn_if_temp_output = original
                    self.assertEqual(len(calls), 1,
                                     '%s 告警接入异常：%r' % (module, calls))
                    self.assertEqual(calls[0][0], str(out_path))
                    self.assertEqual(
                        loud_body, out_path.read_bytes(),
                        '%s 正文因告警改变' % module)
                    quiet_map = out_path.with_suffix('.images_display.json')
                    if loud_map_body is not None or quiet_map.exists():
                        self.assertEqual(
                            loud_map_body, quiet_map.read_bytes(),
                            '%s 显示映射因告警改变' % module)


if __name__ == '__main__':
    unittest.main()
