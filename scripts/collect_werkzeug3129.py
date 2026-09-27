"""Collect upstream-task evidence with raw subprocess outputs; no agent score implied."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'react-agent/eval/cross_repo_evidence/werkzeug-auth-whitespace-3129'
PY = ROOT / 'tmp/werkzeug3129-venv/Scripts/python.exe'

def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def api(route):
    return json.loads(subprocess.check_output(['gh', 'api', route]))

def main():
    D.mkdir(parents=True, exist_ok=True)
    pr = api('repos/pallets/werkzeug/pulls/3129')
    issue = api('repos/pallets/werkzeug/issues/3127')
    write(D/'source.json', {'accessed_at': datetime.now(timezone.utc).isoformat(), 'pr': pr, 'issue': issue})
    snapshots = {}
    for stage, commit in [('before', pr['base']['sha']), ('after', pr['head']['sha'])]:
        archive = D / f'{stage}-source.tar.gz'
        with archive.open('wb') as f:
            subprocess.run(['gh', 'api', f'repos/pallets/werkzeug/tarball/{commit}'], stdout=f, check=True)
        dest = ROOT/'tmp'/f'werkzeug3129-{stage}'
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(dest, filter='data')
        snapshots[stage] = next(dest.glob('*/src'))
    hidden = D/'acceptance/hidden-tests/check_auth.py'
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text('''import sys
sys.path.insert(0, sys.argv[1])
import werkzeug
from werkzeug.datastructures import WWWAuthenticate
print("imported", werkzeug.__file__, flush=True)
for scheme in ("bearer", "basic", "digest"):
    value = WWWAuthenticate(scheme).to_header()
    print(scheme, repr(value), flush=True)
    assert value == scheme.title(), (scheme, value)
assert WWWAuthenticate("bearer", token="abc123").to_header() == "Bearer abc123"
assert WWWAuthenticate("basic", {"realm": "private"}).to_header() == 'Basic realm=private'
print("acceptance passed", flush=True)
''', encoding='utf-8')
    # Tests execute outside source snapshots. Only snapshots are intended for agent input.
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    for stage in ('before', 'after'):
        for attempt in (1, 2):
            cmd = [str(PY), '-I', str(hidden), str(snapshots[stage])]
            started = datetime.now(timezone.utc).isoformat()
            run = subprocess.run(cmd, cwd=snapshots[stage].parent, env=env, capture_output=True, timeout=60)
            target = D/stage if attempt == 1 else D/stage/'repeat'
            target.mkdir(parents=True, exist_ok=True)
            (target/'stdout.log').write_bytes(run.stdout)
            (target/'stderr.log').write_bytes(run.stderr)
            result = {'status': 'passed' if run.returncode == 0 else 'failed', 'exit_code': run.returncode, 'command': cmd, 'started_at': started, 'commit': pr['base' if stage == 'before' else 'head']['sha']}
            write(target/'test-result.json', result)
            write(target/'trajectory.json', {'kind': 'test_execution', 'agent_generated': False, 'steps': [result]})
            assert run.returncode == (1 if stage == 'before' else 0), run.stderr.decode(errors='replace')
            if stage == 'before':
                assert b'AssertionError' in run.stderr and b"Bearer " in run.stdout
    write(D/'acceptance/test-result.json', json.loads((D/'after/test-result.json').read_text()))
    freeze = subprocess.check_output([str(PY), '-m', 'pip', 'freeze']).decode()
    (D/'requirements.lock').write_text(freeze, encoding='utf-8')
    write(D/'metadata.json', {'python': subprocess.check_output([str(PY), '--version']).decode().strip(), 'requirements': freeze, 'offline_execution': True, 'isolation': 'dedicated venv; -I subprocess; evaluator tests outside repository snapshot', 'agent_evaluation_performed': False})
    task = {'task_id': D.name, 'status': 'candidate', 'repository': 'pallets/werkzeug', 'issue_url': issue['html_url'], 'issue_title': issue['title'], 'issue_body': issue['body'], 'issue_author': issue['user']['login'], 'base_commit': pr['base']['sha'], 'fix_commit': pr['head']['sha'], 'problem_statement': 'Parameterless WWW-Authenticate has invalid trailing whitespace.', 'expected_behavior': 'Emit scheme only; preserve tokens and parameters.', 'reproduction_command': json.loads((D/'before/test-result.json').read_text())['command'], 'failing_test': 'parameterless Bearer header equality', 'environment': 'metadata.json', 'image': 'dedicated Windows Python venv', 'acceptance_test': 'acceptance/hidden-tests/check_auth.py', 'evidence_dir': D.relative_to(ROOT).as_posix(), 'split': 'unassigned'}
    write(D/'task.json', task)
    def manifest():
        files = [p for p in D.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts]
        write(D/'manifest.json', {'status': task['status'], 'verified': task['status']=='verified', 'acceptance_status': 'passed', 'evidence_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, 'evidence_files': [{'path':p.relative_to(ROOT).as_posix(), 'size':p.stat().st_size} for p in files]})
    manifest()
    from validate_cross_repo_evidence import validate
    result = validate(task, ROOT)
    assert result['status'] == 'verified', result
    task['status'] = 'verified'
    write(D/'task.json', task)
    manifest()
    assert validate(task, ROOT)['status'] == 'verified'
    ledger_path = ROOT/'react-agent/eval/cross_repo_task_candidates.json'
    ledger = json.loads(ledger_path.read_text())
    ledger.setdefault('placeholder_history', []).extend(t for t in ledger['tasks'] if not t.get('issue_url'))
    ledger['tasks'] = [t for t in ledger['tasks'] if t.get('issue_url') and t['task_id'] != D.name]
    ledger['tasks'].append(task)
    ledger['unfilled_task_slots'] = 6-len(ledger['tasks'])
    ledger['golden_count'] = 0
    ledger['selection_rule'] = 'Select real reproducible defects across repositories; placeholders are not real tasks. Golden selection requires separate diversity and isolation review.'
    write(ledger_path, ledger)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
