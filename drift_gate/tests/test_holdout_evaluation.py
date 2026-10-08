"""W10: holdout split, frozen expectations, blind review packets, adjudication and statistics."""
import json

import pytest

from drift_gate.adapters import holdout as h
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.core import evaluation_stats as stats
from drift_gate.desktop.package_git_check import source

POLICY = {'rules': [{'id': 'api', 'when': {'any_changed': ['src/**']},
                     'require': {'groups': [{'name': 'docs', 'any_changed': ['docs/api.md'], 'content': 'api-routes'}]},
                     'severity': 'blocker'}]}


def case(case_id, family, *, doc, expected_decision, gate, support='supported', broken=False, repository=None):
    api = {'path': 'src/api.py', 'status': 'modified', 'patch': '@@\n-x\n+y\n',
           'before_source': source('/old'), 'after_source': 'def (:\n' if broken else source('/new')}
    docs = {'path': 'docs/api.md', 'status': 'modified', 'patch': '@@\n+x\n', 'after_source': doc,
            'document_input_state': 'available'}
    return {'case_id': case_id, 'repository': repository or f'org/{family}', 'source_family': family,
            'policy': POLICY, 'changed_files': [api, docs], 'drift_ignores': [], 'evaluated_on': '2026-10-08',
            'expected': {'gate': gate, 'rules': {'api': {'decision': expected_decision, 'support': support,
                                                          'known_violation': expected_decision == 'violated'}}}}


CANDIDATES = {'cases': [
    case('a1', 'fam-a', doc='GET /old\n', expected_decision='violated', gate='fail'),
    case('a2', 'fam-a', doc='GET /new\n', expected_decision='satisfied', gate='pass'),
    case('b1', 'fam-b', doc='GET /new\n', expected_decision='satisfied', gate='pass'),
    case('c1', 'fam-c', doc='GET /old\n', expected_decision='violated', gate='fail'),
    case('d1', 'fam-d', doc='GET /new\n', expected_decision='undetermined', gate='fail', support='unsupported', broken=True),
    case('e1', 'fam-e', doc='GET /old\n', expected_decision='violated', gate='fail'),
]}


def test_split_keeps_whole_families_and_excludes_regression_sources():
    held, development = h.split(CANDIDATES, seed='s', holdout_fraction=0.5, regression_families=('fam-e',))
    held_families = {c['source_family'] for c in held['cases']}
    dev_families = {c['source_family'] for c in development['cases']}
    assert held_families and not held_families & dev_families and 'fam-e' not in held_families
    again, _ = h.split(CANDIDATES, seed='s', holdout_fraction=0.5, regression_families=('fam-e',))
    assert again == held
    shared = {'cases': [case('x1', 'f1', doc='', expected_decision='satisfied', gate='pass', repository='org/same'),
                        case('x2', 'f2', doc='', expected_decision='satisfied', gate='pass', repository='org/same')]}
    with pytest.raises(h.HoldoutError, match='both splits'):
        h.split(shared, seed='s', holdout_fraction=0.5)


def test_wilson_and_kappa_reference_values():
    assert stats.wilson(0, 0) == (None, None)
    low, high = stats.wilson(8, 10)
    assert (low, high) == (0.4902, 0.9433)  # standard Wilson 95% interval for 8/10
    assert stats.cohen_kappa([('a', 'a'), ('b', 'b'), ('a', 'b'), ('b', 'b')]) == 0.5
    assert stats.cohen_kappa([('a', 'a'), ('a', 'a')]) is None


def full_holdout():
    held = {'schema': h.CASES, 'split': 'holdout', 'cases': CANDIDATES['cases'][:5]}
    return h.freeze(held, protocol='p1')


def test_freeze_pin_run_and_errors_stay_in_denominators(tmp_path):
    digest = h.write_once(tmp_path / 'frozen.json', full_holdout())
    with pytest.raises(h.HoldoutError, match='never overwritten'):
        h.write_once(tmp_path / 'frozen.json', full_holdout())
    frozen, pinned = h.read_pinned(tmp_path / 'frozen.json', digest, h.FROZEN)
    with pytest.raises(h.HoldoutError, match='pinned'):
        h.read_pinned(tmp_path / 'frozen.json', '0' * 64, h.FROZEN)
    results = h.run_frozen(frozen, pinned)
    decisions = {u['case_id']: u['decision'] for u in results['units']}
    assert decisions['a1'] == 'violated' and decisions['a2'] == 'satisfied' and decisions['d1'] == 'undetermined'
    assert len(results['units']) == 5 and results['engine']['authenticated'] is False


def test_packet_is_blind_and_scores_keep_label_sources_apart(tmp_path):
    frozen = full_holdout()
    packet = h.review_packet(frozen, instructions='x')
    text = json.dumps(packet)
    assert 'expected' not in text and 'actual' not in text and 'decision' not in text
    truth = {'a1': 'violated', 'a2': 'satisfied', 'b1': 'satisfied', 'c1': 'violated', 'd1': 'undecidable'}
    gates = {'a1': 'fail', 'a2': 'pass', 'b1': 'pass', 'c1': 'fail', 'd1': 'fail'}
    reviews = []
    for item in packet['items']:
        cid = item['case_id']
        label = truth[cid] if item['kind'] == 'rule' else gates[cid]
        reviews.append({'item_id': item['item_id'], 'reviewer_id': 'gpt-a', 'reviewer_kind': 'llm-proxy', 'label': label})
        flipped = 'satisfied' if (item['kind'] == 'rule' and cid == 'c1') else label
        reviews.append({'item_id': item['item_id'], 'reviewer_id': 'gpt-b', 'reviewer_kind': 'llm-proxy', 'label': flipped})
    labels = h.adjudicate(packet, reviews)
    assert labels['unresolved'] == [{'item_id': 'c1::api', 'source': 'llm-proxy',
                                     'votes': {'gpt-a': 'violated', 'gpt-b': 'satisfied'}}]
    resolved = h.adjudicate(packet, reviews, [{'item_id': 'c1::api', 'source': 'llm-proxy', 'label': 'violated'}])
    assert not resolved['unresolved'] and resolved['agreement']['llm-proxy']['cohen_kappa'] is not None
    results = h.run_frozen(frozen, 'f' * 64)
    report = h.score_all(results, resolved)
    proxy = report['by_label_source']['llm-proxy']['obligations']
    assert report['by_label_source']['human'] is None and 'not blind ground truth' in report['independence']
    assert proxy['confirmed_violation_precision']['denominator'] == 2
    assert proxy['confirmed_violation_recall'] == {'numerator': 2, 'denominator': 2, 'value': 1.0,
                                                   'wilson95': list(stats.wilson(2, 2))}
    assert proxy['engine_outcomes_in_denominator']['undetermined'] == 1   # U kept, not dropped
    assert proxy['appropriate_unsupported_hold']['numerator'] == 1
    with pytest.raises(h.HoldoutError, match='reviewer_kind'):
        h.adjudicate(packet, [{**reviews[0], 'reviewer_kind': 'model'}])


def test_cli_end_to_end_without_overwrites(tmp_path, capsys):
    (tmp_path / 'candidates.json').write_text(json.dumps(CANDIDATES))

    def cli(*args):
        with pytest.raises(SystemExit) as exit:
            run_cli(['holdout', *args])
        out = json.loads(capsys.readouterr().out)
        return exit.value.code, out

    code, split = cli('split', '--input', str(tmp_path / 'candidates.json'), '--holdout-fraction', '0.5',
                      '--out', str(tmp_path / 'holdout.json'), '--out-development', str(tmp_path / 'dev.json'))
    assert code == 0 and split['holdout_cases'] > 0
    _, frozen = cli('freeze', '--input', str(tmp_path / 'holdout.json'), '--out', str(tmp_path / 'frozen.json'))
    _, results = cli('run', '--frozen', str(tmp_path / 'frozen.json'), '--frozen-sha256', frozen['frozen_sha256'],
                     '--out', str(tmp_path / 'results.json'))
    _, packet = cli('packet', '--frozen', str(tmp_path / 'frozen.json'), '--frozen-sha256', frozen['frozen_sha256'],
                    '--out', str(tmp_path / 'packet.json'))
    items = json.loads((tmp_path / 'packet.json').read_text())['items']
    with open(tmp_path / 'r.jsonl', 'w') as stream:
        for item in items:
            stream.write(json.dumps({'item_id': item['item_id'], 'reviewer_id': 'person-1', 'reviewer_kind': 'human',
                                     'label': item['allowed_labels'][0]}) + '\n')
    _, labels = cli('adjudicate', '--packet', str(tmp_path / 'packet.json'), '--reviews', str(tmp_path / 'r.jsonl'),
                    '--out', str(tmp_path / 'labels.json'))
    _, metrics = cli('score', '--results', str(tmp_path / 'results.json'), '--results-sha256',
                     results['results_sha256'], '--labels', str(tmp_path / 'labels.json'),
                     '--out', str(tmp_path / 'metrics.json'))
    assert metrics['metrics_sha256']
    code, error = cli('freeze', '--input', str(tmp_path / 'holdout.json'), '--out', str(tmp_path / 'frozen.json'))
    assert code == 2 and 'never overwritten' in error['error']['message']
