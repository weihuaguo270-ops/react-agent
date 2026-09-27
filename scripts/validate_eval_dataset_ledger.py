"""Build or validate the source inventory; inventory is not execution evidence."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / 'react-agent/eval/eval_dataset_ledger.json'
SOURCES = {
    'real_task': ('react-agent/eval/software_task_dataset_manifest.json', 'tasks', 'task_id'),
    'synthetic_failure': ('agent-delivery-sandbox/dataset/manifest.json', 'cases', 'case_id'),
    'rule_regression': ('trace-debugger/fixtures/failure_golden/manifest.json', 'cases', 'id'),
    'contract_fixture': ('llm-eval-engine/examples/fixtures/evidence_manifest/multimodal.json', 'samples', 'sample_id'),
}

def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))

def inventory():
    records = []
    for kind, (path, key, id_key) in SOURCES.items():
        source = read(path)
        for item in source[key]:
            digest = item.get('input_sha256', '')
            placeholder = bool(digest and len(set(digest)) == 1)
            if kind == 'real_task':
                for field in ('issue_url', 'base_commit', 'test_command', 'hidden_test_command', 'allowed_paths', 'repository_cluster', 'build'):
                    if not item.get(field):
                        raise ValueError(f"{item[id_key]} missing {field}")
                if len(set(item['base_commit'])) == 1 or placeholder:
                    raise ValueError('Real task has a placeholder fingerprint')
            records.append({
                'sample_id': item[id_key] if kind == 'real_task' else kind + ':' + item[id_key],
                'source_id': item[id_key], 'data_kind': kind,
                'source_uri': path, 'source_sha256': hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                'repository_cluster': item.get('repository_cluster', path.split('/')[0]),
                'split': item.get('split', 'unspecified'),
                'independent_held_out': False,
                'synthetic': kind != 'real_task', 'placeholder_hash': placeholder,
                'acceptance_status': 'not_reverified',
                'issue_url': item.get('issue_url'),
            })
    return records

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync', action='store_true', help='Refresh inventory and invalidate prior verification counts')
    parser.add_argument('--mark-rule-regression-verified', action='store_true', help='Record the completed golden regression run')
    args = parser.parse_args()
    data = json.loads(LEDGER.read_text(encoding='utf-8'))
    expected = inventory()
    queue = read(data['candidate_queue']['source'])['candidates']
    if args.sync:
        data['records'] = expected
        for kind in SOURCES:
            data['summary'][kind].update(count=sum(r['data_kind'] == kind for r in expected), verified=0, verification_status='not_reverified')
        data['candidate_queue'].update(count=len(queue), repositories=len({c['repository'] for c in queue}))
        data['limitations'] = [
            '真实任务只有 3 条且全部来自 FastAPI，不能代表跨项目泛化。',
            '合成样例、规则回归、契约样例和候选队列不计入真实任务成功率。',
            'split 标签不证明独立性；当前独立 held-out 真实任务为 0。',
            '本账本登记来源，未重新验证 Agent 验收结果；verified 为 0 不否定历史运行。',
        ]
        LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.mark_rule_regression_verified:
        for record in data['records']:
            if record['data_kind'] == 'rule_regression':
                record['acceptance_status'] = 'verified_by_trace_debugger_golden'
        data['summary']['rule_regression']['verified'] = data['summary']['rule_regression']['count']
        data['summary']['rule_regression']['verification_status'] = 'verified'
        LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    comparable = [{k: v for k, v in r.items() if k != 'acceptance_status'} for r in data['records']]
    expected_comparable = [{k: v for k, v in r.items() if k != 'acceptance_status'} for r in expected]
    if comparable != expected_comparable:
        raise ValueError('Inventory differs from source manifests; review changes then run --sync')
    counts = Counter(r['data_kind'] for r in expected)
    if len({r['sample_id'] for r in expected}) != len(expected):
        raise ValueError('Duplicate sample IDs')
    for kind, count in counts.items():
        if data['summary'][kind]['count'] != count:
            raise ValueError(f'{kind}: count mismatch')
        if kind != 'rule_regression' and data['summary'][kind]['verified'] != 0:
            raise ValueError(f'{kind}: unsupported verification claim')
    policy = data['policy']
    if policy != {'real_task_success_rate_includes': ['real_task'], 'synthetic_failure_counts_as': 'recovery_rate_only', 'rule_regression_counts_as': 'regression_pass_rate_only', 'contract_fixture_counts_as': 'contract_validation_rate_only'}:
        raise ValueError('Invalid statistical policy')
    candidate = data['candidate_queue']
    if candidate['eligible_as_real_task'] is not False or candidate['count'] != len(queue) or candidate['repositories'] != len({c['repository'] for c in queue}):
        raise ValueError('Candidate queue accounting mismatch')
    print(json.dumps({'valid': True, 'record_count': len(expected), 'counts': counts, 'independent_held_out_real_tasks': 0}, ensure_ascii=False))

if __name__ == '__main__':
    main()
