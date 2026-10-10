"""Qt teardown: closures over ``self`` connected to signals crash PySide6 when the object is destroyed.

Desktop runs 37754952843 and 38035946798 printed every test as passed and then died in interpreter
shutdown ("Fatal Python error: Segmentation fault", no Python frame). Reproduced locally with
PySide6 6.12.0: a ``QDialog`` whose child button signal is connected to ``lambda: ... self ...``
crashes when the dialog is deleted; a bound method does not.
"""
import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _self_closures(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'connect'
                and node.args and isinstance(node.args[0], ast.Lambda)
                and any(isinstance(n, ast.Name) and n.id == 'self' for n in ast.walk(node.args[0]))):
            found.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    return found


def test_no_signal_is_connected_to_a_lambda_over_self():
    offenders = [hit for path in sorted((ROOT / 'drift_gate/desktop').glob('*.py')) for hit in _self_closures(path)]
    assert offenders == [], 'connect a bound method instead: ' + ', '.join(offenders)


DIALOG = '''
import gc
from PySide6.QtWidgets import QApplication
app = QApplication([])
from drift_gate.desktop.review_dialog import ReviewDialog
from drift_gate.tests.test_subscription_review import scan
dialog = ReviewDialog(scan())
dialog.close()
del dialog
gc.collect()
print("deleted")
'''


@pytest.mark.parametrize('attempt', range(3))
def test_review_dialog_deletion_does_not_crash_the_interpreter(attempt):
    pytest.importorskip('PySide6.QtWidgets')
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': str(ROOT)}
    completed = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', DIALOG], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0 and 'deleted' in completed.stdout, completed.stderr[-1500:]
