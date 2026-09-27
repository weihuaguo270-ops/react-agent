import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
queue = json.loads((ROOT / 'react-agent/eval/github_task_review_queue.json').read_text(encoding='utf-8'))
targets = {'pydantic/pydantic', 'encode/httpx'}
rows = [c for c in queue['candidates'] if c['repository_name'] in targets]
required = {'issue_url', 'base_commit', 'public_test', 'hidden_test', 'allowed_paths', 'license_confirmation', 'runtime_image', 'repository_cluster'}
missing = {repo: sorted(required) for repo in sorted(targets)}
for row in rows:
    missing[row['repository_name']] = sorted(set(missing[row['repository_name']]) & set(row.get('missing', [])))
print(json.dumps({'valid': True, 'repositories': len(targets), 'candidates': len(rows), 'missing_by_repository': missing, 'eligible': 0}, ensure_ascii=False))
