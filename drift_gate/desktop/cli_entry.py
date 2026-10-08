"""Headless CLI and teardown tracing inside the packaged app (design W16).

``DriftGate --cli <args>`` runs the same CLI as ``drift-gate`` inside the frozen
executable, so evidence storage, verification, replay and run journals can be
checked in the shipped artifact rather than only in a source checkout. Windowed
builds may have no console streams; callers should use ``--out-json``.

``DRIFT_GATE_TEARDOWN_TRACE=<file>`` records timestamped shutdown events and
enables faulthandler on that file, so a crash during Qt teardown leaves Python
stacks for diagnosis. Tracing observes the existing shutdown order; it does not
change it.
"""
import os
import sys
import time

_TRACE = None


def run_cli_passthrough(argv):
    """Return None when argv is not a CLI invocation; otherwise exit with the CLI's code."""
    if len(argv) < 2 or argv[1] != '--cli':
        return None
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    from drift_gate.adapters.cli.runner import run_cli
    run_cli(argv[2:])
    return 0


def trace(event, **details):
    global _TRACE
    path = os.environ.get('DRIFT_GATE_TEARDOWN_TRACE')
    if not path:
        return
    if _TRACE is None:
        import faulthandler
        _TRACE = open(path, 'a', encoding='utf-8', buffering=1)
        faulthandler.enable(_TRACE, all_threads=True)
        import atexit
        atexit.register(lambda: trace('atexit'))
    fields = ' '.join(f'{key}={value}' for key, value in sorted(details.items()))
    _TRACE.write(f'{time.monotonic():.6f} pid={os.getpid()} {event} {fields}\n')
