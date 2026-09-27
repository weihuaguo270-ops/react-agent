import json
import unittest
from run_blind_pilot import classify_patch, compact_messages, outcome_fields, progress_message, request_tools, tool_history_entry, response_violation


class OutcomeTests(unittest.TestCase):
 def test_patch_classification(self):
  self.assertEqual(classify_patch('',False),'patch_empty')
  self.assertEqual(classify_patch('--- a/README.md\n+++ b/README.md\n',True),'patch_invalid')
  src='--- a/src/pkg.py\n+++ b/src/pkg.py\n@@ -1 +1 @@\n-a\n+b\n'
  self.assertEqual(classify_patch(src,False),'hidden_failed')
  self.assertEqual(classify_patch(src,True),'verified_fix')

 def test_patch_hash_uses_file_bytes(self):
  import hashlib
  payload='--- a/src/pkg.py\n+++ b/src/pkg.py\n'
  self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), hashlib.sha256(payload.encode('utf-8')).hexdigest())
 def test_terminal_rejects_historical_shell_and_mixed_batches(self):
  shell={'function':{'name':'shell','arguments':'{}'}}
  submit={'function':{'name':'submit','arguments':'{}'}}
  for calls in ([shell], [submit,shell], [shell,submit], [], [submit,submit]):
   with self.subTest(calls=calls):
    self.assertIsNotNone(response_violation(calls,True))
  self.assertIsNone(response_violation([submit],True))
  self.assertIsNone(response_violation([shell],False))

 def test_unknown_tool_rejected_before_batch_execution(self):
  self.assertIsNotNone(response_violation([{'function':{'name':'shell'}},{'function':{'name':'unknown'}}],False))

 def test_history_preserves_command_exit_and_edit(self):
  call={'id':'1','function':{'name':'shell','arguments':json.dumps({'command':"python -c \"open('x','w').write('y')\""})}}
  response={'content':json.dumps({'exit_code':1,'stdout':'','stderr':'missing dependency'})}
  entry=tool_history_entry(call,response)
  self.assertEqual(entry['exit_code'],1)
  self.assertTrue(entry['possible_edit'])
  self.assertIn('missing dependency',entry['output_tail'])

 def test_compaction_keeps_structured_history(self):
  messages=[{'role':'system','content':'s'},{'role':'user','content':'u'}]
  for i in range(6):
   call={'id':str(i),'type':'function','function':{'name':'shell','arguments':json.dumps({'command':f'cmd {i}'})}}
   messages.extend([{'role':'assistant','content':'','tool_calls':[call]},
                    {'role':'tool','tool_call_id':str(i),'content':json.dumps({'exit_code':i,'stdout':f'out {i}','stderr':''})}])
  compacted=compact_messages(messages,keep_pairs=2)
  summary=json.loads(compacted[2]['content'].split(': ',1)[1])
  self.assertEqual(summary[-1]['command'],'cmd 3')
  self.assertEqual(summary[-1]['exit_code'],3)
  self.assertEqual(len(compacted),7)

 def test_terminal_stage_only_allows_submit(self):
  tools,choice,terminal=request_tools(49000,64000,4000,20,40)
  self.assertTrue(terminal)
  self.assertEqual([t['function']['name'] for t in tools],['submit'])
  self.assertEqual(choice,'required')

 def test_work_stage_keeps_shell_and_submit(self):
  tools,choice,terminal=request_tools(1000,64000,4000,2,40)
  self.assertFalse(terminal)
  self.assertIsNone(choice)
  self.assertEqual([t['function']['name'] for t in tools],['shell','submit'])

 def test_low_budget_requests_honest_submission(self):
  text=progress_message(49000,64000,4000,20,40)['content']
  self.assertIn('11000 tokens remain',text)
  self.assertIn('call submit',text)
  self.assertIn('incomplete checks',text)

 def test_last_turn_requests_submission(self):
  self.assertIn('call submit',progress_message(1000,64000,4000,39,40)['content'])

 def test_early_turn_allows_work(self):
  self.assertIn('Batch related inspections',progress_message(0,64000,4000,0,40)['content'])

 def test_half_budget_without_edits_requires_implementation(self):
  text=progress_message(32000,64000,4000,8,40,False)['content']
  self.assertIn('No repository changes',text)
  self.assertIn('implement the smallest concrete fix now',text)

 def test_half_budget_with_edits_keeps_normal_guidance(self):
  text=progress_message(32000,64000,4000,8,40,True)['content']
  self.assertNotIn('No repository changes',text)


 def test_acceptance_does_not_hide_budget_stop(self):
  result=outcome_fields('budget_exhausted',True,61707,64000)
  self.assertEqual(result['termination_reason'],'budget_exhausted')
  self.assertEqual(result['run_status'],'budget_exhausted')
  self.assertTrue(result['hidden_passed'])
  self.assertTrue(result['budget_compliant'])

 def test_acceptance_does_not_hide_violation(self):
  result=outcome_fields('budget_violation',True,65000,64000)
  self.assertFalse(result['budget_compliant'])
  self.assertEqual(result['run_status'],'budget_violation')

 def test_submit_remains_distinct_from_grade(self):
  result=outcome_fields('submitted',False,1000,64000)
  self.assertEqual(result['termination_reason'],'submitted')
  self.assertFalse(result['hidden_passed'])

 def test_terminal_submit_remains_distinct(self):
  result=outcome_fields('terminal_submitted',False,53000,64000)
  self.assertEqual(result['termination_reason'],'terminal_submitted')
  self.assertTrue(result['budget_compliant'])

 def test_terminal_protocol_violation_remains_distinct(self):
  result=outcome_fields('protocol_violation',False,53000,64000)
  self.assertEqual(result['termination_reason'],'protocol_violation')
  self.assertTrue(result['budget_compliant'])


if __name__=='__main__':
 unittest.main()
