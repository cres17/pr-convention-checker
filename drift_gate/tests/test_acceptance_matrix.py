"""Every acceptance-matrix row (design section 18) names tests that exist, and external needs stay explicit."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def matrix():
    spec = importlib.util.spec_from_file_location('acceptance_matrix', ROOT / 'scripts/acceptance_matrix.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MATRIX


def test_matrix_covers_a01_to_a17_and_every_test_is_collected():
    rows = matrix()
    assert [row['id'] for row in rows] == [f'A{n:02d}' for n in range(1, 18)]
    nodes = sorted({test for row in rows for test in row['tests']})
    completed = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', *nodes],
                               cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    collected = {line.split('[')[0] for line in completed.stdout.splitlines() if '::' in line}
    assert set(nodes) <= collected


def test_rows_needing_outside_evidence_say_so():
    rows = {row['id']: row for row in matrix() if row.get('external')}
    assert {'A10', 'A16', 'A17'} <= set(rows)  # isolated workflow, installed apps, independent labels
    assert all(row['external']['state'] in {'present', 'partial', 'missing'} for row in rows.values())
    assert rows['A17']['external']['state'] == 'missing'
