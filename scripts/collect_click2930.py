"""Rebuild and collect evidence from frozen upstream commits, not agent runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
D = ROOT/'react-agent/eval/cross_repo_evidence/click-typed-flag-2930'

def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2)+'\n', encoding='utf-8')

def run(cmd, folder, cwd):
    folder.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, timeout=180)
    (folder/'stdout.log').write_bytes(r.stdout)
    (folder/'stderr.log').write_bytes(r.stderr)
    result = {'command': [str(x) for x in cmd], 'cwd':str(cwd), 'exit_code':r.returncode, 'status':'passed' if r.returncode==0 else 'failed', 'captured_at':datetime.now(timezone.utc).isoformat()}
    write(folder/'test-result.json', result)
    return r, result

def main():
    task=json.loads((D/'task.json').read_text())
    work=Path(tempfile.mkdtemp(prefix='click2930-', dir=ROOT/'tmp'))
    venv=work/'venv'
    subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
    py=venv/'Scripts/python.exe'
    cmd=[py,'-m','pip','install','--no-index','--find-links',D/'wheels','colorama==0.4.6']
    r,_=run(cmd,D/'environment/install',work)
    assert r.returncode==0, r.stderr.decode(errors='replace')
    (D/'requirements.lock').write_text('colorama==0.4.6\n')
    snapshots={}
    for stage,sha in [('before',task['base_commit']),('after',task['fix_commit'])]:
        archive=D/f'{stage}-source.tar.gz'
        with archive.open('wb') as f:
            subprocess.run(['gh','api',f'repos/pallets/click/tarball/{sha}'],stdout=f,check=True)
        dest=work/stage
        dest.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(dest,filter='data')
        snapshots[stage]=next(dest.glob('*/src'))
    repro=D/'reproduction.py'
    repro.write_text("import sys\nsys.path.insert(0,sys.argv[1])\nimport click\nfrom click.testing import CliRunner\n@click.command()\n@click.option('--transpose',is_flag=True,type=str)\ndef cli(transpose):\n    click.echo(repr(transpose))\nr=CliRunner().invoke(cli,['--transpose'])\nprint('imported',click.__file__,flush=True)\nprint('cli_exit',r.exit_code,'output',repr(r.output),flush=True)\nassert r.exit_code==0\nassert r.output==\"'True'\\n\", 'target_flag_behavior'\n",encoding='utf-8')
    hidden=D/'acceptance/hidden-tests/check_flags.py'
    for stage in ('before','after'):
        for attempt in (1,2):
            folder=D/stage if attempt==1 else D/stage/'repeat'
            test=repro if stage=='before' else hidden
            r,result=run([py,'-I',test,snapshots[stage]],folder,snapshots[stage].parent)
            result['commit']=task['base_commit' if stage=='before' else 'fix_commit']
            write(folder/'test-result.json',result)
            write(folder/'trajectory.json',{'kind':'test_execution','agent_generated':False,'steps':[result]})
            assert r.returncode==(1 if stage=='before' else 0),r.stderr.decode(errors='replace')
            if stage=='before':
                assert b'target_flag_behavior' in r.stderr and b'cli_exit 0' in r.stdout
    # Check hidden tests discriminate the baseline too, not just the public repro.
    r,_=run([py,'-I',hidden,snapshots['before']],D/'acceptance/baseline',work)
    assert r.returncode==1 and b'target_flag_behavior' in r.stderr
    write(D/'acceptance/test-result.json',json.loads((D/'after/test-result.json').read_text()))
    write(D/'metadata.json',{'venv_creation':[sys.executable,'-m','venv',str(venv)],'python':subprocess.check_output([str(py),'--version']).decode().strip(),'dependencies':subprocess.check_output([str(py),'-m','pip','freeze']).decode(),'source_roots':{k:str(v) for k,v in snapshots.items()},'offline_test_execution':True,'agent_evaluation_performed':False,'isolation':'-I dedicated venv; evaluator scripts outside source roots; no actual agent mounted yet'})
    task.update(status='candidate',verified=False,problem_statement='Explicitly typed flags fail to activate on CLI invocation.',expected_behavior='Flag activation and default toggling preserve explicit type conversion.',reproduction_command=json.loads((D/'before/test-result.json').read_text())['command'],failing_test='target_flag_behavior',environment='metadata.json',image='Windows Python isolated venv',acceptance_test='acceptance/hidden-tests/check_flags.py',missing=[])
    def seal():
        write(D/'task.json',task)
        files=[p for p in D.rglob('*') if p.is_file() and p.name not in ('manifest.json','source-manifest.json') and '__pycache__' not in p.parts]
        write(D/'manifest.json',{'verified':task['verified'],'status':task['status'],'acceptance_status':'passed','evidence_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'evidence_files':[{'path':p.relative_to(ROOT).as_posix(),'size':p.stat().st_size} for p in files]})
    seal()
    from validate_cross_repo_evidence import validate
    assert validate(task,ROOT)['status']=='verified'
    task.update(status='verified',verified=True)
    seal()
    assert validate(task,ROOT)['status']=='verified'
    p=ROOT/'react-agent/eval/cross_repo_task_candidates.json'
    ledger=json.loads(p.read_text())
    ledger['tasks']=[task if t['task_id']==task['task_id'] else t for t in ledger['tasks']]
    ledger['counts']={'verified_tasks':5,'source_fixed_candidates':0,'unfilled_task_slots':1,'golden':0}
    write(p,ledger)
    print(json.dumps(validate(task,ROOT)))

if __name__=='__main__':
    main()
