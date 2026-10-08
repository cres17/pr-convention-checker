"""Isolated analysis worker processes (design W12).

Each job runs in a fresh ``python -I`` process in its own session/process
group, inside an empty temporary working directory, with credential variables
removed. The child receives immutable source bytes and their SHA-256 on stdin
and returns one bounded JSON object on stdout; the parent checks the echoed
digest, operation and profile before admitting the result.

Restrictions and their actual strength:
- POSIX resource limits on address space (Linux only; macOS does not enforce
  RLIMIT_AS), CPU seconds, file size (no file writes) and open files.
- A Python audit hook blocks socket creation/connection, subprocess spawn and
  opening files outside the interpreter and installed packages. Native code
  (e.g. a grammar library) does not pass through audit hooks: this is a guard
  against accidental Python-level access, not an OS sandbox.
- Timeout and cancellation kill the whole process group (POSIX) so spawned
  grandchildren end too; on Windows only the child process is terminated.
"""
from base64 import b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

OPS = {'python-routes': ('python-fastapi-routes', '1'), 'python-env': ('python-env-literals', '1'),
       'tree-sitter-nodes': ('tree-sitter-node-count', '1')}
TEST_OPS = ('sleep', 'crash', 'flood', 'bad-output', 'spawn-child', 'net', 'read-file', 'alloc', 'parser-init')
DEFAULT_LIMITS = {'timeout_seconds': 60, 'max_output_bytes': 4_000_000, 'max_memory_bytes': 1_500_000_000,
                  'max_cpu_seconds': 60, 'max_input_bytes': 2_000_000}


@dataclass(frozen=True)
class WorkerResult:
    status: str            # ok | timeout | cancelled | crash | invalid-output | oversized-output | failed | queue-full
    value: object = None
    detail: str = ''
    elapsed_seconds: float = 0.0
    limits_unapplied: tuple = ()   # OS limits the worker could not set (reported by the worker itself)

    def to_dict(self):
        return {'status': self.status, 'value': self.value, 'detail': self.detail,
                'elapsed_seconds': round(self.elapsed_seconds, 3), 'limits_unapplied': list(self.limits_unapplied)}


CHILD = r'''
import json, os, sys
request = json.loads(sys.stdin.buffer.read())
limits = request['limits']
try:
    import resource
except ImportError:
    resource = None
wanted = [('cpu', 'RLIMIT_CPU', limits['max_cpu_seconds']), ('file-size', 'RLIMIT_FSIZE', 0),
          ('open-files', 'RLIMIT_NOFILE', 64)]
applied, unapplied = [], []
if sys.platform.startswith('linux'):
    wanted.insert(0, ('memory', 'RLIMIT_AS', limits['max_memory_bytes']))
else:
    unapplied.append('memory')  # macOS does not enforce RLIMIT_AS for ordinary allocations
for name, kind, value in wanted:
    try:
        resource.setrlimit(getattr(resource, kind), (value, value))
        applied.append(name)
    except (AttributeError, ValueError, OSError):
        unapplied.append(name)  # reported to the caller, never silently assumed
allowed = tuple(sorted({os.path.realpath(p) for p in sys.path if p} | {os.path.realpath(sys.prefix),
                os.path.realpath(sys.base_prefix)} | set(request.get('read_roots', []))))
def audit(event, args):
    if event in ('socket.__new__', 'socket.connect', 'socket.bind', 'socket.getaddrinfo'):
        raise PermissionError('network access is blocked in the analysis worker')
    if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork'):
        raise PermissionError('process creation is blocked in the analysis worker')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        path = os.path.realpath(os.fsdecode(args[0]))
        if not path.startswith(allowed):
            raise PermissionError('file access outside the worker allowlist is blocked')
op, payload = request['op'], request['payload']
if op in ('spawn-child', 'net', 'read-file', 'parser-init', 'alloc', 'sleep', 'crash', 'flood', 'bad-output') \
        and os.environ.get('DRIFT_GATE_WORKER_TEST_OPS') != '1':
    raise SystemExit(64)
if op == 'spawn-child':
    import subprocess
    marker = payload.get('marker', '61.2345')
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(' + marker + ')'])
    import time; time.sleep(60)
sys.addaudithook(audit)
import base64, hashlib
raw = base64.b64decode(payload['source_b64'])
if hashlib.sha256(raw).hexdigest() != payload['sha256']:
    raise SystemExit(65)
out = {'op': op, 'input_sha256': payload['sha256'], 'profile': request['profile'],
       'limits_applied': applied, 'limits_unapplied': unapplied}
try:
    if op == 'python-routes':
        from drift_gate.core.evaluation.api_schema import extract_routes, UnsupportedContract
        try:
            out['value'] = sorted(map(list, extract_routes(raw.decode('utf-8'))))
        except UnsupportedContract as exc:
            out['value'], out['open'] = None, str(exc)
    elif op == 'python-env':
        from drift_gate.core.evaluation.environment import environment_facts
        facts = environment_facts(raw.decode('utf-8'))
        out['value'] = None if facts.uncertain else sorted(facts.keys)
    elif op == 'tree-sitter-nodes':
        from drift_gate.adapters.grammar_resources import get_parser
        tree = get_parser(payload.get('language', 'python')).parse(raw)
        count, stack = 0, [tree.root_node]
        while stack:
            node = stack.pop(); count += 1; stack.extend(node.children)
        out['value'] = {'nodes': count, 'has_error': tree.root_node.has_error}
    elif op == 'sleep':
        import time; time.sleep(payload.get('seconds', 60)); out['value'] = 'late'
    elif op == 'crash':
        os.abort()
    elif op == 'flood':
        sys.stdout.write('x' * payload.get('bytes', 10_000_000)); sys.stdout.flush(); raise SystemExit(0)
    elif op == 'bad-output':
        out['input_sha256'] = '0' * 64; out['value'] = []
    elif op == 'net':
        import socket; socket.create_connection(('example.invalid', 80), timeout=1)
    elif op == 'read-file':
        open(payload['path']).read()
    elif op == 'alloc':
        block = bytearray(payload['bytes']); out['value'] = len(block)
    elif op == 'parser-init':
        from drift_gate.adapters.grammar_resources import get_parser
        get_parser('not-a-shipped-language')
    else:
        raise SystemExit(66)
except PermissionError as exc:
    out['error'] = 'blocked: ' + str(exc)
except MemoryError:
    out['error'] = 'memory-limit'
except Exception as exc:
    out['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
sys.stdout.write(json.dumps(out))
'''


def _environment():
    from drift_gate.adapters.engine_artifact import isolated_environment
    return isolated_environment({'PYTHONDONTWRITEBYTECODE': '1'})


def run_job(op, source, *, limits=None, language='python', extra=None, cancel=None):
    """Run one analysis job in a fresh isolated process; never raises for worker faults."""
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    if op not in OPS and op not in TEST_OPS:
        raise ValueError(f'unknown worker op {op}')
    raw = source if isinstance(source, bytes) else source.encode('utf-8')
    extra = dict(extra or {})
    if op == 'tree-sitter-nodes':
        try:
            from tree_sitter_language_pack import cache_dir
            extra['read_roots'] = [*extra.get('read_roots', []), os.path.realpath(cache_dir())]
        except ImportError:
            pass
    if len(raw) > limits['max_input_bytes']:
        return WorkerResult('failed', detail='input exceeds worker input limit')
    digest = sha256(raw).hexdigest()
    profile = list(OPS.get(op, ('test', '0')))
    # The engine package itself (editable installs live outside sys.path) is readable.
    package_root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    request = json.dumps({'op': op, 'profile': profile, 'limits': limits,
                          'read_roots': [package_root, *(str(p) for p in (extra or {}).get('read_roots', []))],
                          'payload': {'source_b64': b64encode(raw).decode('ascii'), 'sha256': digest,
                                      'language': language, **(extra or {}).get('payload', {})}}).encode()
    started = time.monotonic()
    workdir = tempfile.mkdtemp(prefix='driftgate-worker-')
    posix = os.name == 'posix'
    env = _environment()
    if (extra or {}).get('test_ops'):
        env['DRIFT_GATE_WORKER_TEST_OPS'] = '1'
    # -B: no bytecode writes (file writes are limited to 0 bytes in the child).
    process = subprocess.Popen([sys.executable, '-I', '-B', '-c', CHILD], cwd=workdir, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=posix)
    output, overflow, done = bytearray(), [False], threading.Event()

    def reader():
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            if len(output) + len(chunk) > limits['max_output_bytes']:
                overflow[0] = True
                _kill(process, posix)
                break
            output.extend(chunk)
        done.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        process.stdin.write(request)
        process.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    status = None
    deadline = started + limits['timeout_seconds']
    while not done.wait(0.05):
        if cancel is not None and cancel.is_set():
            status = 'cancelled'
        elif time.monotonic() > deadline:
            status = 'timeout'
        if status:
            _kill(process, posix)
            break
    if status is None:
        _kill(process, posix)  # reap any grandchildren left in the group
    process.wait(timeout=10)
    thread.join(timeout=5)
    stderr = process.stderr.read()[-2000:].decode('utf-8', 'replace')
    elapsed = time.monotonic() - started
    _cleanup(workdir)
    if status:
        # A reply that arrives after the deadline or cancellation is discarded by construction.
        return WorkerResult(status, detail=f'killed process group after {elapsed:.2f}s', elapsed_seconds=elapsed)
    if overflow[0]:
        return WorkerResult('oversized-output', detail=f'output exceeded {limits["max_output_bytes"]} bytes',
                            elapsed_seconds=elapsed)
    if process.returncode != 0:
        return WorkerResult('crash', detail=f'exit {process.returncode}: {stderr[-500:]}', elapsed_seconds=elapsed)
    try:
        data = json.loads(bytes(output))
    except ValueError:
        return WorkerResult('invalid-output', detail='worker output is not one JSON object', elapsed_seconds=elapsed)
    if (not isinstance(data, dict) or data.get('op') != op or data.get('input_sha256') != digest
            or data.get('profile') != profile):
        return WorkerResult('invalid-output', detail='worker output does not bind to the request', elapsed_seconds=elapsed)
    unapplied = tuple(data.get('limits_unapplied') or ())
    if 'error' in data:
        return WorkerResult('failed', detail=data['error'], elapsed_seconds=elapsed, limits_unapplied=unapplied)
    return WorkerResult('ok', data.get('value'), data.get('open', ''), elapsed, unapplied)


def _kill(process, posix):
    try:
        if posix:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _cleanup(directory):
    import shutil
    shutil.rmtree(directory, ignore_errors=True)


class WorkerPool:
    """Bounded concurrency with an explicit queue limit; overflow is rejected, not buffered."""

    def __init__(self, *, max_workers=2, max_queue=8, limits=None):
        if max_workers < 1 or max_queue < 0:
            raise ValueError('pool requires at least one worker and a nonnegative queue')
        self.max_workers, self.max_queue, self.limits = max_workers, max_queue, limits
        self._slots = threading.Semaphore(max_workers)
        self._lock = threading.Lock()
        self._pending = 0

    def submit(self, op, source, **kwargs):
        with self._lock:
            if self._pending >= self.max_workers + self.max_queue:
                return None  # caller records queue-full; nothing was started
            self._pending += 1
        result = {}
        done = threading.Event()

        def work():
            with self._slots:
                try:
                    result['value'] = run_job(op, source, limits=self.limits, **kwargs)
                finally:
                    with self._lock:
                        self._pending -= 1
                    done.set()

        threading.Thread(target=work, daemon=True).start()
        return result, done

    def run(self, op, source, **kwargs):
        handle = self.submit(op, source, **kwargs)
        if handle is None:
            return WorkerResult('queue-full', detail='worker queue is saturated')
        result, done = handle
        done.wait()
        return result['value']
