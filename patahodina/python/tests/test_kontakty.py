"""Skutečné běhy obou Python programů nad všemi formáty a vadnými vstupy."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {'json': '.json', 'xml': '.xml', 'vcard': '.vcf', 'csv': '.csv', 'txt': '.txt'}


class KontaktyTests(unittest.TestCase):
    def run_program(self, variant, *args, text=None):
        return subprocess.run([sys.executable, str(ROOT / variant / 'main.py'), *args],
                              input=text, capture_output=True, text=True,
                              cwd=tempfile.gettempdir(), timeout=10)

    def test_all_formats_and_interactive_selection(self):
        expected = None
        for variant in ('sablony', 'dedicnost'):
            for fmt in FORMATS:
                with self.subTest(variant=variant, fmt=fmt):
                    result = self.run_program(variant, fmt)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Načteno kontaktů: 6', result.stdout)
                    self.assertIn('Anna Nováková', result.stdout)
                    expected = expected or result.stdout
                    self.assertEqual(result.stdout, expected)
                    interactive = self.run_program(variant, text=fmt+'\n')
                    self.assertEqual(interactive.returncode, 0, interactive.stderr)
                    self.assertIn(expected, interactive.stdout)

    def test_errors_do_not_print_partial_database(self):
        for variant in ('sablony', 'dedicnost'):
            for fmt, suffix in FORMATS.items():
                with self.subTest(variant=variant, fmt=fmt), tempfile.TemporaryDirectory() as tmp:
                    self.assertNotEqual(self.run_program(variant, fmt, tmp).returncode, 0)
                    Path(tmp, 'vadny'+suffix).write_text('vadný vstup', encoding='utf-8')
                    result = self.run_program(variant, fmt, tmp)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('vadny'+suffix, result.stderr)
                    self.assertNotIn('Načteno', result.stdout)
            self.assertNotEqual(self.run_program(variant, 'pdf').returncode, 0)
            with tempfile.TemporaryDirectory() as tmp:
                missing = str(Path(tmp) / 'neexistuje')
                self.assertNotEqual(self.run_program(variant, 'json', missing).returncode, 0)


if __name__ == '__main__':
    unittest.main()
