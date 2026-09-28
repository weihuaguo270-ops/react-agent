import hashlib
import json
import sys
from pathlib import Path

REQUIRED = ('repository','issue_url','issue_title','issue_body','issue_author','base_commit','problem_statement','expected_behavior',
            'reproduction_command','failing_test','environment','image','acceptance_test','evidence_dir')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(task, root):
    # Evidence task.json is authoritative for promoted candidates; the portfolio
    # ledger may intentionally contain only discovery metadata.
    if task.get('evidence_dir'):
        local_task_path = root / task['evidence_dir'] / 'task.json'
        if local_task_path.exists():
            local_task = json.loads(local_task_path.read_text(encoding='utf-8'))
            merged = dict(task)
            merged.update(local_task)
            task = merged
    missing = [k for k in REQUIRED if not task.get(k)]
    if missing:
        return {'task_id': task.get('task_id'), 'status': 'review_queue_only', 'missing': missing}
    evidence = root / task['evidence_dir']
    acceptance_files = sorted((evidence / 'acceptance' / 'hidden-tests').glob('*.py'))
    required_files = [evidence/'task.json', evidence/'metadata.json', evidence/'before'/'trajectory.json', evidence/'before'/'test-result.json', evidence/'before'/'stdout.log', *acceptance_files, evidence/'after'/'test-result.json', evidence/'after'/'stdout.log', evidence/'manifest.json']
    absent = [str(p.relative_to(root)) for p in required_files if not p.exists()]
    if absent:
        reason = 'missing_base_commit' if not task.get('base_commit') else 'missing_post_fix_evidence' if any('/after/' in p for p in absent) else 'missing_evidence'
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': reason, 'missing_evidence': absent}
    hashes = task.get('evidence_sha256', {})
    manifest = json.loads((evidence/'manifest.json').read_text(encoding='utf-8'))
    if not acceptance_files:
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': 'missing_acceptance'}
    for entry in manifest.get('evidence_files', []):
        p = root / entry['path']
        digest = manifest.get('evidence_sha256', {}).get(str(p.relative_to(root)))
        if not p.is_file() or p.stat().st_size != entry['size'] or sha(p) != digest:
            return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': 'manifest_integrity_failed', 'path': entry['path']}
    hashes = {**hashes, **manifest.get('evidence_sha256', {})}
    hash_targets = [p for p in required_files if p.name != 'manifest.json']
    bad_hashes = [str(p.relative_to(root)).replace('\\\\', '/') for p in hash_targets if hashes.get(str(p.relative_to(root)).replace('\\\\', '/')) != sha(p)]
    if bad_hashes:
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'bad_hashes': bad_hashes}
    before = json.loads((evidence/'before'/'test-result.json').read_text(encoding='utf-8'))
    after = json.loads((evidence/'after'/'test-result.json').read_text(encoding='utf-8'))
    if before.get('status') != 'failed' or before.get('exit_code') in (None, 0):
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': 'reproduction_unstable'}
    if after.get('status') != 'passed' or after.get('exit_code') != 0:
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': 'missing_post_fix_evidence'}
    if manifest.get('acceptance_status') != 'passed':
        return {'task_id': task.get('task_id'), 'status': 'candidate', 'reason': 'missing_acceptance'}
    return {'task_id': task['task_id'], 'status': 'verified'}

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    path = root / 'react-agent/eval/cross_repo_task_candidates.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    results = [validate(t, root) for t in data.get('tasks', [])]
    print(json.dumps({'valid': all(r['status'] == 'verified' for r in results) if results else True, 'results': results, 'verified': sum(r['status'] == 'verified' for r in results)}, ensure_ascii=False))
