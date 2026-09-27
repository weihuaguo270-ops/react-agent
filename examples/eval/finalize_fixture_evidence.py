"""Finalize evidence entries that have deterministic fixture-backed outcomes."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'artifacts/software-delivery'
def write(task, test, decision, findings):
 d=BASE/task
 (d/'test-result.json').write_text(json.dumps(test,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (d/'acceptance.json').write_text(json.dumps({'status':'fixture_verified','decision':decision,'findings':findings},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 write('pass_existing_fix',{'status':'passed','source':'existing task metadata','public_test':'passed','hidden_test':'passed','exit_code':0},'pass',[])
 write('tests_still_fail',{'status':'failed','source':'trajectory_bad.json','exit_code':1},'hold',[{'type':'tool_error','source':'trajectory_bad.json'}])
 print('finalized 2 deterministic fixture-backed evidence bundles; 3 remain pending')
if __name__=='__main__': main()
