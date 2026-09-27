"""Single-attempt model pilot: host API controller, networkless shell container."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
P=ROOT/'react-agent/eval/blind_pilot_v1'
SHELL_TOOL={'type':'function','function':{'name':'shell','description':'Run a shell command in the isolated baseline repository. Use this for inspection, editing, and focused tests.','parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command']}}}
SUBMIT_TOOL={'type':'function','function':{'name':'submit','description':'Submit the current working tree for external hidden acceptance. Call this immediately after implementing the minimal fix and running focused tests. Do not continue exploring after submission.','parameters':{'type':'object','properties':{'summary':{'type':'string'}},'required':['summary']}}}
TOOLS=[SHELL_TOOL,SUBMIT_TOOL]

def save(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')

def outcome_fields(termination_reason, hidden_passed, usage, budget):
 return {'run_status':termination_reason,'termination_reason':termination_reason,
         'hidden_passed':hidden_passed,'budget_compliant':usage<=budget}

def progress_message(usage, budget, guard, turns, max_turns, has_changes=True):
 remaining=max(0,budget-guard-usage)
 final=remaining<=12000 or max_turns-turns<=3
 stalled=usage>=budget//2 and not has_changes
 return {'role':'user','content':(
  f'Controller budget update: {usage}/{budget} cumulative provider tokens used; '
  f'{remaining} tokens remain before the request guard; {max_turns-turns} model turns remain. '
  'Each request includes prompt tokens. '
  + ('No repository changes have been detected after half the token budget. Stop investigating, '
     'implement the smallest concrete fix now, run one focused check, and submit.' if stalled and not final else
     'Finish now: call submit with the current patch and honestly list incomplete checks. '
     'Do not claim success for unrun or failing checks.' if final else
     'Batch related inspections, make the minimal correction, run focused checks, then submit.'))}

def tree_fingerprint(repo):
 h=hashlib.sha256()
 for path in sorted(p for p in repo.rglob('*') if p.is_file()):
  rel=path.relative_to(repo)
  if '__pycache__' in rel.parts or '.pytest_cache' in rel.parts: continue
  h.update(rel.as_posix().encode());h.update(b'\0');h.update(path.read_bytes())
 return h.digest()

def tool_history_entry(call, response):
 try:
  command=json.loads(call['function']['arguments']).get('command','')
 except (KeyError, TypeError, json.JSONDecodeError):
  command='[unparseable command]'
 try:
  data=json.loads(response.get('content','{}'))
 except json.JSONDecodeError:
  data={}
 output=(data.get('stderr') or data.get('stdout') or '').replace('\n',' ')
 edit_markers=('sed -i','apply_patch','write_text','open(','cat >','tee ','perl -pi')
 return {'command':command[:240],'exit_code':data.get('exit_code'),
         'possible_edit':any(marker in command for marker in edit_markers),
         'output_tail':output[-240:]}

def compact_messages(messages, keep_pairs=2):
 """Keep API context bounded while retaining the complete audit log on disk."""
 system=messages[0]
 initial=messages[1]
 tail=messages[2:]
 pairs=[];i=0
 while i<len(tail):
  if tail[i].get('role')=='assistant' and tail[i].get('tool_calls'):
   end=i+1
   while end<len(tail) and tail[end].get('role')=='tool': end+=1
   pairs.append(tail[i:end]);i=end
  else:i+=1
 recent=[m for pair in pairs[-keep_pairs:] for m in pair]
 history=[]
 for pair in pairs[:-keep_pairs]:
  assistant=pair[0]
  calls={call.get('id'):call for call in assistant.get('tool_calls',[])}
  for m in pair[1:]:
   call=calls.get(m.get('tool_call_id'))
   if call and call.get('function',{}).get('name')=='shell':
    history.append(tool_history_entry(call,m))
 summary='Prior tool history compressed as JSON: '+json.dumps(history[-10:],ensure_ascii=False)
 return [system,initial,{'role':'user','content':summary},*recent]

def request_tools(usage, budget, guard, turns, max_turns):
 terminal=budget-guard-usage<=12000 or max_turns-turns<=3
 if terminal:
  # Some OpenAI-compatible gateways ignore the named-function form. With a
  # single exposed tool, `required` is equivalent and broadly supported.
  return [SUBMIT_TOOL], 'required', True
 return TOOLS, None, False

def docker(args,timeout=60):
 return subprocess.run(['docker',*map(str,args)],capture_output=True,timeout=timeout)

def response_violation(calls, terminal):
 """Validate the entire batch before executing any tool, including submit."""
 if terminal and (len(calls)!=1 or calls[0].get('function',{}).get('name')!='submit'):
  return 'terminal stage requires exactly one submit call'
 if any(c.get('function',{}).get('name') not in ('shell','submit') for c in calls):
  return 'response contains an unavailable tool'
 return None

def classify_patch(patch_text, hidden_passed):
 """Classify the submitted source diff independently from termination state."""
 if not patch_text.strip():
  return 'patch_empty'
 paths=[]
 for line in patch_text.splitlines():
  if line.startswith(('--- a/','+++ b/')):
   path=line[6:]
   if path != '/dev/null': paths.append(path)
 if not paths or not all(p.startswith(('src/','pydantic/','httpx/','werkzeug/')) for p in paths):
  return 'patch_invalid'
 return 'verified_fix' if hidden_passed else 'hidden_failed'

def isolated(image,repo,extra=()):
 return ['run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','1000:1000','--pids-limit','128','--memory','1g','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=128m','--mount',f'type=bind,source={repo},target=/workspace','-w','/workspace',*extra,'--entrypoint','python',image]

def grade(image,repo,hidden,out):
 source='/workspace/src' if (repo/'src').exists() else '/workspace'
 driver="import sys,runpy,pathlib; sys.path.insert(0,sys.argv[1]); p=next(pathlib.Path('/hidden').glob('*.py')); sys.argv=[str(p),sys.argv[1]]; d=runpy.run_path(str(p),run_name='__main__'); fs=[v for k,v in d.items() if k.startswith('test_') and callable(v)]; [f() for f in fs]; print('hidden checks completed')"
 r=docker([*isolated(image,repo,['--mount',f'type=bind,source={hidden},target=/hidden,readonly']),'-B','-c',driver,source])
 out.mkdir(parents=True,exist_ok=True);(out/'stdout.log').write_bytes(r.stdout);(out/'stderr.log').write_bytes(r.stderr)
 save(out/'result.json',{'exit_code':r.returncode,'status':'passed' if r.returncode==0 else 'failed'})
 return r.returncode

def main():
 budget=int(os.getenv('BLIND_TOKEN_BUDGET','64000'))
 guard=int(os.getenv('BLIND_TOKEN_GUARD','4000'))
 max_completion=int(os.getenv('BLIND_MAX_COMPLETION','2048'))
 max_seconds=int(os.getenv('BLIND_MAX_SECONDS','900'))
 max_turns=int(os.getenv('BLIND_MAX_TURNS','40'))
 manifest=json.loads((P/'split_manifest.json').read_text()); ledger=json.loads((ROOT/'react-agent/eval/cross_repo_task_candidates.json').read_text())
 selected_split=os.getenv('BLIND_SPLIT','development')
 manifest['tasks']=[t for t in manifest['tasks'] if t['split']==selected_split]
 selected={x.strip() for x in os.getenv('BLIND_TASK_IDS','').split(',') if x.strip()}
 if selected:
  manifest['tasks']=[t for t in manifest['tasks'] if t['task_id'] in selected]
 if not manifest['tasks']:
  raise ValueError('no development tasks selected')
 tasks={t['task_id']:t for t in ledger['tasks']}
 image=docker(['image','inspect','agent-blind-pilot:20260919','--format','{{.Id}}']).stdout.decode().strip();assert image.startswith('sha256:')
 label=os.getenv('BLIND_RUN_LABEL','dev-v10')
 runroot=P/'runs'/(label+'-'+time.strftime('%Y%m%d-%H%M%S'));runroot.mkdir(parents=True)
 save(runroot/'protocol.json',{'scope':selected_split,'split':selected_split,'model':'deepseek-flash','total_token_budget':budget,'seconds':max_seconds,'max_turns':max_turns,'revision':'v10','budget_method':'provider_total_tokens_post_response','selected_tasks':[t['task_id'] for t in manifest['tasks']],'change':'v9 controls plus host-side full-batch validation; terminal stage requires exactly one submit.','guard_tokens':guard,'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
 # Baseline gate happens before spending any model tokens.
 for t in manifest['tasks']:
  tid=t['task_id']; repo=ROOT/t['input_dir']/'repo'; hidden=ROOT/tasks[tid]['evidence_dir']/'acceptance/hidden-tests'
  rc=grade(image,repo,hidden,runroot/tid/'baseline')
  err=(runroot/tid/'baseline/stderr.log').read_text(errors='replace')
  assert rc!=0 and not any(x in err for x in ('ModuleNotFoundError','ImportError','SystemError')), (tid,err)
 config=json.loads((ROOT/'react-agent/llm_config.json').read_text(encoding='utf-8'))['providers']['deepseek']
 env={}
 for line in (ROOT/'react-agent/.env').read_text(encoding='utf-8').splitlines():
  if '=' in line and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);env[k.strip()]=v.strip().strip('\"\'')
 key=os.getenv(config['api_key_env']) or env[config['api_key_env']]
 results=[]
 for t in manifest['tasks']:
  tid=t['task_id'];out=runroot/tid; bundle=ROOT/t['input_dir'];repo=out/'repo';shutil.copytree(bundle/'repo',repo)
  name='blind-'+uuid.uuid4().hex[:12]
  cmd=isolated(image,repo,['--mount',f'type=bind,source={bundle / "problem.md"},target=/input/problem.md,readonly'])
  # Persistent shell container holds no model/API credentials.
  cmd[1:2]=['-d','--name',name]
  r=docker([*cmd,'-c','import time; time.sleep(1000)']);assert r.returncode==0,r.stderr.decode()
  start=time.monotonic(); usage=0; completion=0;status='running';turns=0
  baseline_fingerprint=tree_fingerprint(repo)
  messages=[{'role':'system','content':(P/'prompt.md').read_text()},{'role':'user','content':(bundle/'problem.md').read_text()}]
  try:
   while time.monotonic()-start<max_seconds and turns<max_turns:
    # Keep original conversation on disk. Only old tool output is compacted in API input.
    request_messages=compact_messages(messages)
    request_messages.append(progress_message(usage,budget,guard,turns,max_turns,tree_fingerprint(repo)!=baseline_fingerprint))
    # Leave headroom for the provider's next prompt framing and usage accounting.
    # The provider reports prompt plus completion tokens per request, so a hard
    # 32k cumulative ceiling needs a conservative pre-request guard.
    available=budget - guard - usage
    if available<=0: status='budget_exhausted';break
    tools,tool_choice,terminal=request_tools(usage,budget,guard,turns,max_turns)
    body={'model':'deepseek-flash','messages':request_messages,'tools':tools,'temperature':0,'max_tokens':min(max_completion,available),'thinking':{'type':'disabled'}}
    if tool_choice is not None: body['tool_choice']=tool_choice
    save(out/f'request-{turns+1:02}.json',{'body':body,'budget_method':'provider_total_tokens_post_response','cumulative_usage_before':usage})
    req=urllib.request.Request(config['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=min(120,max(1,max_seconds-(time.monotonic()-start)))) as response: data=json.load(response)
    turns+=1;save(out/f'model-{turns:02}.json',data)
    u=data.get('usage');assert u and isinstance(u.get('total_tokens'),int),'missing usage'
    usage+=u['total_tokens'];completion+=u.get('completion_tokens',0)
    if usage>budget:
     status='budget_violation'; save(out/'budget-violation.json',{'usage':usage,'budget':budget,'turn':turns}); break
    msg=data['choices'][0]['message'];messages.append(msg)
    calls=msg.get('tool_calls',[])
    violation=response_violation(calls,terminal)
    if violation:
     status='protocol_violation'
     save(out/'protocol-violation.json',{'reason':violation,'turn':turns,'terminal':terminal,'calls':calls})
     break
    if not calls:status='model_finished';break
    for call in calls:
     if call['function']['name']=='submit':
      save(out/'submission.json',json.loads(call['function']['arguments']))
      status='terminal_submitted' if terminal else 'submitted'; break
     if call['function']['name']!='shell': raise ValueError('unexpected tool')
     command=json.loads(call['function']['arguments'])['command']
     remaining=max_seconds-(time.monotonic()-start)
     if remaining<=0: raise TimeoutError('wall budget')
     try:
      r=docker(['exec',name,'bash','-o','pipefail','-lc',command],timeout=min(45,remaining))
      output={'exit_code':r.returncode,'stdout':r.stdout.decode(errors='replace')[-3000:],'stderr':r.stderr.decode(errors='replace')[-1000:]}
     except subprocess.TimeoutExpired:
      status='tool_timeout';raise TimeoutError('shell timeout')
     save(out/f'tool-{turns:02}-{calls.index(call)}.json',{'command':command,**output})
     messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(output)})
    if status in ('submitted','terminal_submitted','protocol_violation'): break
   else:status='turn_limit' if turns>=max_turns else 'time_exhausted'
  except Exception as e:
   status='error:'+type(e).__name__
  finally:
   docker(['rm','-f',name]); save(out/'conversation.json',messages)
  patch=[]
  base=bundle/'repo'
  paths=set(p.relative_to(base) for p in base.rglob('*') if p.is_file())|set(p.relative_to(repo) for p in repo.rglob('*') if p.is_file())
  for rel in sorted(paths):
   if '__pycache__' in rel.parts or '.pytest_cache' in rel.parts:continue
   a=base/rel;b=repo/rel
   if b.is_symlink():raise ValueError('symlink in submission')
   old=a.read_text(errors='replace').splitlines(True) if a.exists() else []
   new=b.read_text(errors='replace').splitlines(True) if b.exists() else []
   patch.extend(difflib.unified_diff(old,new,fromfile='a/'+rel.as_posix(),tofile='b/'+rel.as_posix()))
  (out/'patch.diff').write_text(''.join(patch),encoding='utf-8')
  rc=grade(image,repo,ROOT/tasks[tid]['evidence_dir']/'acceptance/hidden-tests',out/'acceptance')
  hidden_passed=rc==0
  patch_text=(out/'patch.diff').read_text(encoding='utf-8')
  patch_bytes=(out/'patch.diff').stat().st_size
  result={'task_id':tid,'split':t['split'],'run_status':status,'hidden_passed':hidden_passed,'patch_status':classify_patch(patch_text,hidden_passed),'patch_bytes':patch_bytes,'patch_sha256':hashlib.sha256((out/'patch.diff').read_bytes()).hexdigest(),'elapsed_seconds':round(time.monotonic()-start,2),'tokens':usage,'completion_tokens':completion,'cost':None,'cost_reason':'provider billing price not verified','regression_suite':'only bundled hidden assertions; no full upstream suite','image':image}
  result.update(outcome_fields(status,hidden_passed,usage,budget))
  save(out/'result.json',result);results.append(result);save(runroot/'results.json',results);print(json.dumps(result),flush=True)
 save(runroot/'results.json',{'task_verified_count':6,'scope':'development only','agent_runs':len(results),'hidden_pass_rate':sum(r['hidden_passed'] for r in results)/len(results),'results':results,'golden_count':0,'run_dir':str(runroot)})

if __name__=='__main__':main()
