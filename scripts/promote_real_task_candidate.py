"""Validate a manually completed cross-repository task promotion record."""
import json
import sys
from pathlib import Path

REQUIRED = ('task_id', 'repository', 'issue_url', 'base_commit', 'split',
            'test_command', 'hidden_test_command', 'allowed_paths',
            'license', 'runtime_image', 'repository_cluster')

def validate(task):
    missing = [key for key in REQUIRED if not task.get(key)]
    if missing:
        raise ValueError('missing required fields: ' + ', '.join(missing))
    if task['split'] not in {'dev', 'golden', 'held_out'}:
        raise ValueError('split must be dev, golden, or held_out')
    if len(task['base_commit']) != 40 or set(task['base_commit']) <= {'0'}:
        raise ValueError('base_commit must be a real 40-character commit')
    if not str(task['issue_url']).startswith('https://github.com/'):
        raise ValueError('issue_url must be a public GitHub issue URL')
    if not isinstance(task['test_command'], list) or not isinstance(task['hidden_test_command'], list):
        raise ValueError('test commands must be argv lists')
    if not isinstance(task['allowed_paths'], list) or not task['allowed_paths']:
        raise ValueError('allowed_paths must be non-empty')
    return True

if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('cross_repo_task_candidates.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    tasks = data.get('tasks', data if isinstance(data, list) else [])
    if not tasks and data.get('status') == 'review_required':
        print(json.dumps({'valid': True, 'eligible_tasks': 0, 'held_out': 0, 'status': 'review_required'}, ensure_ascii=False))
        raise SystemExit(0)
    if not tasks:
        raise SystemExit('no tasks found')
    eligible = [task for task in tasks if task.get('status') != 'review_queue_only']
    for task in eligible:
        if task.get('status') == 'review_queue_only':
            continue
        validate(task)
    print(json.dumps({'valid': True, 'eligible_tasks': len(eligible), 'held_out': sum(t['split'] == 'held_out' for t in eligible)}, ensure_ascii=False))
