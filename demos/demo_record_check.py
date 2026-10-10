import json
import os
import tempfile
from pathlib import Path

os.environ["REACT_AGENT_STEP_WATCHER"] = "1"
td = tempfile.mkdtemp()
log = Path(td) / "failures.jsonl"
traj_dir = Path(td) / "trajectories"
traj_dir.mkdir()
os.environ["REACT_AGENT_FAILURE_LOG"] = str(log)

import react_agent.harness.recorder as rec

rec.TRAJECTORY_DIR = str(traj_dir)

from react_agent.harness.recorder import Trajectory

t = Trajectory("calc 2+2", model="demo")
t.add_tool_call(
    1, "calculator", '{"expression": "2++"}', '{"error": "syntax error"}', 0.2
)
t.add_thought(2, "FINAL ANSWER: failed")
t.set_final_answer("failed")
path = t.save()

saved = json.loads(Path(path).read_text(encoding="utf-8"))
events = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]

print("=== STEP 1 (trajectory JSON) ===")
print(json.dumps(saved["steps"][0], ensure_ascii=False, indent=2))
print("\n=== JSONL events ===")
for e in events:
    slim = {
        k: e[k]
        for k in ("event_type", "step_index", "failure_type", "failure_detail", "action")
        if k in e
    }
    print(json.dumps(slim, ensure_ascii=False))
print(f"\nOK: trajectory={path}")
print(f"OK: jsonl_events={len(events)}")
