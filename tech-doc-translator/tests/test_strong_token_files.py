"""强 token 文件的实际入口与交付依赖，预期来自固定清单。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'skills/tech-doc-translator/scripts'))
from _verification import extract_strong_tokens
import verify_delivery as delivery
import verify_reference_translation as reference


class TokenFilesTest(unittest.TestCase):
    def test_literal_data_and_equivalent_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'tokens.txt').write_text(' .rn \n#\n%tid\n.rn\n\n')
            rest, tokens = extract_strong_tokens(
                ['doc', 'src', '--strong-token', '%tid',
                 '--strong-token-file', 'tokens.txt'], base_dir=tmp)
            self.assertEqual(rest, ['doc', 'src'])
            self.assertEqual(tokens, ['%tid', '.rn', '#'])
            parsed = reference.parse_args(
                ['doc', 'src', '.rn', '--strong-token-file', 'tokens.txt'],
                base_dir=tmp)
            self.assertEqual(parsed['strong_tokens'], ['.rn', '#', '%tid'])
            facts, _ = delivery._check_facts(tmp, 'verify_reference_translation',
                ['doc', 'src', '--strong-token-file', 'tokens.txt'], 1)
            self.assertIsNotNone(facts['files']['strong_token_files'][0][1])

    def test_option_shaped_literal_has_same_cli_result_as_file(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = root/'source.md', root/'target.md'
            source.write_text('# Guide\n\n```shell\nnvcc --use_fast_math\n```\n')
            target.write_text('# Guide（指南）\n\n```shell\nnvcc --use_fast_math\n```\n')
            tokens = root/'tokens.txt'
            tokens.write_text('--use_fast_math\n')
            script = Path(reference.__file__)
            def run(options):
                return subprocess.run([sys.executable, str(script), str(target),
                    str(source), *options], capture_output=True, text=True)
            item = run(['--strong-token', '--use_fast_math'])
            file = run(['--strong-token-file', str(tokens)])
            merged = run(['--strong-token', '--use_fast_math',
                          '--strong-token-file', str(tokens)])
            self.assertEqual(0, item.returncode, item.stderr)
            self.assertEqual((item.returncode, item.stdout),
                             (file.returncode, file.stdout))
            self.assertEqual((item.returncode, item.stdout),
                             (merged.returncode, merged.stdout))
            target.write_text(target.read_text().replace('--use_fast_math', '--slow_math'))
            self.assertNotEqual(0, run(['--strong-token', '--use_fast_math']).returncode)

    def test_bad_inputs_do_not_become_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'bad').write_bytes(b'\xff')
            for args in (['--strong-token', ''], ['--strong-token'],
                         ['--strong-token-file'],
                         ['--strong-token-file', 'missing'],
                         ['--strong-token-file', 'bad']):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    extract_strong_tokens(args, base_dir=tmp)
