"""Integrační kontrola skutečných binárek a chybných vstupů bez dalších balíčků."""
import subprocess
import sys
import tempfile
from pathlib import Path

formats = {'json': '.json', 'xml': '.xml', 'vcard': '.vcf', 'csv': '.csv', 'txt': '.txt'}
expected = None
checks = 0
for binary in sys.argv[1:]:
    def run(*args, input=None):
        return subprocess.run([binary, *map(str, args)], input=input, text=True,
                              capture_output=True, cwd='/tmp', timeout=10)
    for fmt, suffix in formats.items():
        result = run(fmt)
        assert result.returncode == 0, result.stderr
        assert 'Načteno kontaktů: 6' in result.stdout
        if expected is None:
            expected = result.stdout
        assert result.stdout == expected, (binary, fmt)
        interactive = run(input=fmt+'\n')
        assert interactive.returncode == 0 and expected in interactive.stdout
        checks += 2
        with tempfile.TemporaryDirectory() as tmp:
            assert run(fmt, tmp).returncode != 0  # prázdná složka
            Path(tmp, 'vadny'+suffix).write_text('vadný vstup', encoding='utf-8')
            bad = run(fmt, tmp)
            assert bad.returncode != 0 and 'vadny'+suffix in bad.stderr
            assert 'Načteno' not in bad.stdout
            checks += 2
    assert run('pdf').returncode != 0
    assert run('json', '/neexistujici/slozka/kontaktu').returncode != 0
    checks += 2
print(f'OK: {checks} kontrol; oba programy, všech pět formátů a chybové stavy.')
