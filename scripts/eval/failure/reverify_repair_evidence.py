"""Re-run baseline and existing agent patch; retain raw Docker evidence."""
import json
import hashlib
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / 'src'))
from react_agent.eval.task_manifest import build_runner, load_tasks
from react_agent.eval.software_task_runner import SoftwareTaskRunner

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    assets = ROOT / 'artifacts/software-tasks'
    bundle = ROOT / 'artifacts/software-delivery/repair_then_pass'
    raw = next(t for t in load_tasks(ROOT / 'eval/software_task_dataset_manifest.json') if t['task_id'] == 'fastapi-15974-router-cache-race')
    source = assets / 'runs' / ('_src_' + raw['base_commit'][:12])
    task, runner = build_runner(raw, source, artifact_root=assets)
    run = bundle / 'runs' / uuid.uuid4().hex
    runner = SoftwareTaskRunner(replace(runner.config, artifact_dir=run))
    ready, error = runner.verify_runtime()
    if not ready:
        raise RuntimeError(error)
    workspace = run / 'workspace'
    workspace.parent.mkdir(parents=True)
    # Cached partial clones cannot be cloned locally when promised objects are absent.
    shutil.copytree(source, workspace)
    subprocess.run(['git', 'checkout', '--detach', task.base_commit], cwd=workspace, check=True)
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=workspace).strip():
        raise RuntimeError('Baseline workspace is not clean')
    patch = assets / 'patches/fastapi-15974/agent.patch'
    results = {}
    for stage in ('before', 'after'):
        if stage == 'after':
            subprocess.run(['git', 'apply', '--check', str(patch)], cwd=workspace, check=True)
            subprocess.run(['git', 'apply', str(patch)], cwd=workspace, check=True)
            repair = run / 'repair'
            repair.mkdir()
            shutil.copyfile(patch, repair / 'patch.diff')
            write(repair / 'repair-result.json', {'status': 'applied', 'exit_code': 0, 'patch_source': str(patch.relative_to(ROOT)), 'sha256': hashlib.sha256(patch.read_bytes()).hexdigest(), 'mode': 'existing_agent_patch_replay'})
        result = runner.run(task, workspace=workspace)
        result['captured_at'] = datetime.now(timezone.utc).isoformat()
        results[stage] = result
        write(run / stage / 'trajectory.json', result)
        write(run / stage / 'test-result.json', result)
        (run / stage / 'stdout.log').write_text(result['stdout'], encoding='utf-8')
        (run / stage / 'stderr.log').write_text(result['stderr'], encoding='utf-8')
        print(stage, result['status'], result['exit_code'], flush=True)
    before, after = results['before'], results['after']
    ok = (before['exit_code'] == 1 and before['public_test'].get('status') == 'passed' and before['hidden_test'].get('status') == 'failed' and after['status'] == 'succeeded' and after['exit_code'] == 0 and all(after[k].get('status') == 'passed' for k in ('public_test', 'hidden_test')) and not after['unauthorized_paths'])
    for stage in ('before', 'repair', 'after'):
        shutil.copytree(run / stage, bundle / stage, dirs_exist_ok=True)
    write(bundle / 'task.json', {**raw, 'id': 'repair_then_pass', 'task_hash': task.content_hash(), 'run_directory': str(run.relative_to(ROOT)), 'mode': 'existing_agent_patch_replay', 'trajectory_format': 'raw SoftwareTaskRunner result'})
    write(bundle / 'acceptance.json', {'status': 'verified' if ok else 'review', 'decision': 'pass' if ok else 'review', 'pre_repair': {'test_status': before['status'], 'exit_code': before['exit_code'], 'log': 'before/test-result.json'}, 'post_repair': {'test_status': 'passed' if after['status'] == 'succeeded' else after['status'], 'exit_code': after['exit_code'], 'log': 'after/test-result.json'}, 'reverified': ok, 'mode': 'existing_agent_patch_replay', 'run_directory': str(run.relative_to(ROOT))})
    return 0 if ok else 1

if __name__ == '__main__':
    raise SystemExit(main())
