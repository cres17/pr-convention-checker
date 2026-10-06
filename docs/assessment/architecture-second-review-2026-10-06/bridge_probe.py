"""Real Qt worker response to malformed optional history, without a GUI window."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

workspace = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(workspace))
from PySide6.QtCore import QCoreApplication
from drift_gate.desktop.web_app import DesktopBridge
from drift_gate.desktop.progress_service import save_baseline, extract_requirements
from drift_gate.tests.test_progress_service import project

app = QCoreApplication.instance() or QCoreApplication([])
with TemporaryDirectory(prefix='second-review-bridge-') as directory:
    tmp = Path(directory)
    root = project(tmp)
    data = tmp / 'data'
    save_baseline(root,data,extract_requirements(root,['README.md']))
    target = next(data.glob('*.json')).with_suffix('.history.json')
    target.write_text('{"schema":1,"snapshots":[{}]}',encoding='utf-8')
    bridge = DesktopBridge()
    bridge._progress_dir = lambda: data
    events = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))
    bridge.inspectProgress(str(root),'damaged-history')
    assert bridge.progress_pool.waitForDone(3000)
    app.processEvents()
    assert [event['type'] for event in events] == ['progressError']
    assert events[0]['request_done']
    result = {'damaged_history_events':[event['type'] for event in events],
       'terminal':events[0]['request_done'],'report_delivered':False}
    target.unlink()
    events.clear()
    bridge.inspectProgress(str(root),'repaired-history')
    assert bridge.progress_pool.waitForDone(3000)
    app.processEvents()
    assert [event['type'] for event in events] == ['progressReport','progressHistory']
    result['control_events'] = [event['type'] for event in events]
    bridge.closeDraftSessions()
    (Path(__file__).parent / 'bridge-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
