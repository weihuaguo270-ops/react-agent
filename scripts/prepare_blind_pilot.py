"""Prepare source-only inputs. Never launch agents or expose evaluator evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'react-agent/eval/blind_pilot_v1'
DESCRIPTIONS = {
 'pydantic-identity-review': 'Equivalent RootModel values using a named type alias versus its underlying type compare unequal. Restore equality for equivalent aliases while preserving distinctions between different root types and values.',
 'httpx-identity-review': 'A URL path containing a literal pipe is emitted without percent encoding. Ensure the serialized request path correctly encodes that character and preserves existing escapes and other URL components.',
 'httpx-activity-review': 'URL components over-escape general delimiters. Paths should permit colon, slash, square brackets and at-sign; queries additionally permit question-mark; fragments additionally permit question-mark and hash. Preserve escaping of characters that are not allowed in each component.',
 'werkzeug-auth-whitespace-3129': 'A parameterless WWW-Authenticate challenge has trailing whitespace, causing rejection by HTTP consumers. Emit a valid challenge while preserving challenges with parameters or tokens.',
 'click-typed-flag-2930': 'Command-line flags declared with an explicit type may fail to activate. For example, an is_flag option with type=str yields None when supplied. Correct activation and default-value behavior while preserving explicit flag values and ordinary typed options.',
 'jinja-async-unique-1782': 'With asynchronous template rendering enabled, unique fails after an async-producing filter with an async_generator not iterable error. Support deduplication in asynchronous filter chains while preserving ordinary unique behavior, order, case and attribute handling.'
}

def write(p, obj):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')

def main():
 from validate_cross_repo_evidence import validate
 ledger_path=ROOT/'react-agent/eval/cross_repo_task_candidates.json'
 ledger=json.loads(ledger_path.read_text())
 results=[validate(t,ROOT) for t in ledger['tasks']]
 assert len(results)==6 and all(t['status']=='verified' for t in results), results
 held={'click-typed-flag-2930','jinja-async-unique-1782'}
 OUT.mkdir(parents=True,exist_ok=True)
 plans=[]
 for row in ledger['tasks']:
  tid=row['task_id']; evidence=ROOT/row['evidence_dir']
  task=json.loads((evidence/'task.json').read_text())
  split='held_out_provisional' if tid in held else 'development'
  row.update(status='verified',split=split)
  bundle=OUT/'inputs'/tid
  bundle.mkdir(parents=True,exist_ok=True)
  source=bundle/'repo'
  if source.exists():
   raise RuntimeError(f'Refuse overwriting existing input: {source}')
  with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as temp:
   archive=Path(temp)/'base.tar.gz'
   with archive.open('wb') as f:
    subprocess.run(['gh','api',f"repos/{task['repository']}/tarball/{task['base_commit']}"],stdout=f,check=True)
   archive_hash=hashlib.sha256(archive.read_bytes()).hexdigest()
   with tarfile.open(archive) as tar:
    # Regular files only: no external symlink destinations, Git metadata or hooks.
    for member in tar.getmembers():
     parts=Path(member.name).parts[1:]
     if not member.isfile() or not parts or any(x in ('.git','.agents','.codex') for x in parts): continue
     if '..' in parts or Path(*parts).is_absolute(): raise ValueError(member.name)
     target=source.joinpath(*parts); target.parent.mkdir(parents=True,exist_ok=True)
     target.write_bytes(tar.extractfile(member).read())
  (bundle/'problem.md').write_text(DESCRIPTIONS[tid]+'\n',encoding='utf-8')
  files={p.relative_to(bundle).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.rglob('*') if p.is_file()}
  plans.append({'task_id':tid,'split':split,'repository':task['repository'],'base_commit':task['base_commit'],'input_dir':bundle.relative_to(ROOT).as_posix(),'base_archive_sha256':archive_hash,'input_sha256':files})
 ledger['counts']={'verified_tasks':6,'unfilled_task_slots':0,'golden':0}
 ledger['unfilled_task_slots']=0
 ledger['split_policy']='4 development / 2 provisional held-out; clean eligibility requires fresh model context, input-only mounts, no curator history or network retrieval.'
 write(ledger_path,ledger)
 write(OUT/'split_manifest.json',{'tasks':plans,'golden':0,'held_out_eligibility':'pending isolation attestation; public upstream pretraining exposure cannot be excluded'})
 write(OUT/'run_protocol.json',{'status':'blocked_preflight','blockers':['docker_daemon_unavailable','model_endpoint_and_hard_token_cap_not_configured','input_only_mount_negative_probe_not_run'],'model':None,'model_requirement':'pin exact provider/model version before any run','temperature':0,'attempts_per_task':1,'wall_time_seconds':900,'total_token_budget':32000,'budget_enforcement':'must stop on cumulative provider usage; do not launch with advisory-only cap','tools':['read files','edit files','shell in disposable input-only container'],'network_for_tools':'none','mounts':'only problem.md and baseline repo; never workspace root, Docker socket, credentials, hidden tests, source snapshots or after evidence','prompt_file':'prompt.md','agent_runs':0,'scores':None,'cost':None,'cost_rule':'provider usage times recorded price version; unavailable pricing remains null'})
 write(OUT/'results.json',{'task_verified_count':6,'agent_runs':0,'agent_pass_rate':None,'regression_failures':None,'elapsed_seconds':None,'tokens':None,'actual_cost':None,'golden_count':0})
 (OUT/'prompt.md').write_text('Fix the defect described in /input/problem.md using only the baseline repository in /workspace. Inspect code, implement a minimal correction, and run relevant available tests. Do not retrieve upstream solutions. Do not change tests to hide failures. Leave changes in the working tree and summarize the changes and checks. The evaluator will collect the patch and run separate tests after your process exits.\n',encoding='utf-8')
 print(json.dumps({'verified':6,'development':4,'held_out_provisional':2,'agent_runs':0}))

if __name__=='__main__': main()
