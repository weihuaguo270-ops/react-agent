import json
import os
import urllib.request

root = os.path.dirname(os.path.dirname(__file__))
cfg = json.load(open(os.path.join(root, 'llm_config.json'), encoding='utf-8'))['providers']['deepseek']
env = {}
for line in open(os.path.join(root, '.env'), encoding='utf-8'):
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        env[key.strip()] = value.strip().strip('"\'')
api_key = os.getenv(cfg['api_key_env']) or env[cfg['api_key_env']]
tool = {'type': 'function', 'function': {'name': 'submit', 'description': 'Return a submission summary.', 'parameters': {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']}}}
messages = [{'role': 'system', 'content': 'Compatibility probe. Call the only available submit tool exactly once per request.'}, {'role': 'user', 'content': 'Probe only; do not inspect or modify any repository.'}]
observed = []
for turn in range(2):
    body = {'model': 'deepseek-flash', 'messages': messages, 'tools': [tool], 'tool_choice': 'required', 'temperature': 0, 'max_tokens': 128, 'thinking': {'type': 'disabled'}}
    request = urllib.request.Request(cfg['base_url'].rstrip('/') + '/chat/completions', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    message = data['choices'][0]['message']
    calls = message.get('tool_calls', [])
    names = [call['function']['name'] for call in calls]
    observed.append(names)
    if len(names) != 1 or names[0] != 'submit':
        print(json.dumps({'valid': False, 'turns': observed}))
        raise SystemExit(2)
    messages.extend([message, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': '{"ok":true}'}])
print(json.dumps({'valid': True, 'turns': observed}))
