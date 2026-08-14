"""Agent 对话 + 轨迹查看器 + Eval 评测看板（Flask）"""

import subprocess
import signal
import json
import os
import glob
import time
import sys
from flask import Flask, jsonify, send_from_directory, request
from react_agent.paths import runtime_dir

app = Flask(__name__, static_folder='.', static_url_path='')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAJECTORIES_DIR = str(
    runtime_dir('trajectories', env_var='REACT_AGENT_TRAJECTORY_DIR')
)
REACT_LOOP = os.path.join(BASE_DIR, 'react_loop.py')
REPORTS_DIR = str(runtime_dir('reports', env_var='REACT_AGENT_REPORT_DIR'))


# ── 主页 ──

@app.route('/')
def index():
    """返回本地 dashboard 静态入口。"""
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')


# ── 轨迹 API ──

@app.route('/api/trajectories')
def list_trajectories():
    """按修改时间返回最近 100 条轨迹摘要，跳过损坏文件。"""
    if not os.path.exists(TRAJECTORIES_DIR):
        return jsonify([])
    files = sorted(glob.glob(os.path.join(TRAJECTORIES_DIR, '*.json')),
                   key=os.path.getmtime, reverse=True)
    result = []
    for f in files[:100]:
        try:
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
            result.append({
                'name': os.path.basename(f),
                'query': data.get('query', ''),
                'model': data.get('model', ''),
                'steps': data.get('total_steps', 0),
                'duration': data.get('total_duration_seconds', 0),
                'tokens': data.get('total_tokens_estimated', 0),
                'timestamp': data.get('timestamp', ''),
                'session_id': data.get('session_id', ''),
                'source': data.get('source', ''),
                'final_answer': data.get('final_answer', '')[:80],
            })
        except (json.JSONDecodeError, OSError):
            continue
    return jsonify(result)


@app.route('/api/trajectories/<name>')
def get_trajectory(name):
    """读取一条本地轨迹；该开发路由不提供租户或鉴权隔离。"""
    # 兼容带 traj_ 前缀和不带的情况
    safe_name = name if name.startswith('traj_') else f'traj_{name}'
    for fname in (safe_name, name):
        path = os.path.join(TRAJECTORIES_DIR, fname)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
    return jsonify({'error': 'not found'}), 404


@app.route('/api/trajectories/clear', methods=['POST'])
def clear_trajectories():
    """删除超过保留天数的轨迹；``days=0`` 表示全部删除。"""
    data = request.get_json(force=True)
    days = data.get('days', 0)
    if not os.path.exists(TRAJECTORIES_DIR):
        return jsonify({'message': '没有轨迹文件可删除'})
    files = glob.glob(os.path.join(TRAJECTORIES_DIR, 'traj_*.json'))
    if not files:
        return jsonify({'message': '没有轨迹文件可删除'})
    now = time.time()
    cutoff = now - days * 86400 if days > 0 else now + 1
    removed = 0
    for f in files:
        if days > 0:
            mtime = os.path.getmtime(f)
            if mtime >= cutoff:
                continue
        try:
            os.remove(f)
            removed += 1
        except OSError:
            continue
    msg = f'已删除 {removed} 个轨迹文件' if removed else '没有符合条件的轨迹文件'
    return jsonify({'message': msg})


# ── 对话 API ──

@app.route('/api/chat', methods=['POST'])
def chat():
    """在独立 Python 子进程执行 Agent 查询并返回最新轨迹。

    该接口面向本地调试，继承服务环境且没有用户鉴权，不应直接暴露公网。
    """
    data = request.get_json(force=True)
    query = data.get('query', '')
    if not query:
        return jsonify({'error': 'query 不能为空'}), 400

    try:
        result = subprocess.run(
            [sys.executable, REACT_LOOP, query],
            capture_output=True, text=True, timeout=60,
            cwd=BASE_DIR,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()[:500] if result.stderr else ''

        # 查找最新轨迹文件
        latest_traj = None
        if os.path.exists(TRAJECTORIES_DIR):
            files = sorted(glob.glob(os.path.join(TRAJECTORIES_DIR, 'traj_*.json')),
                           key=os.path.getmtime, reverse=True)
            if files:
                with open(files[0], encoding='utf-8') as fh:
                    latest_traj = json.load(fh)

        return jsonify({
            'stdout': stdout,
            'stderr': stderr,
            'trajectory': latest_traj,
            'exit_code': result.returncode,
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': '执行超时（60秒）', 'stdout': '', 'stderr': '', 'trajectory': None}), 504
    except Exception as e:
        return jsonify({'error': str(e), 'stdout': '', 'stderr': '', 'trajectory': None}), 500


# ── Eval 评测 API ──

@app.route('/api/eval/reports')
def list_eval_reports():
    """列出所有评测报告"""
    if not os.path.exists(REPORTS_DIR):
        return jsonify([])
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, 'eval_*.json')),
                   key=os.path.getmtime, reverse=True)
    result = []
    for f in files[:50]:
        try:
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
            result.append({
                'report_id': data.get('report_id', ''),
                'timestamp': data.get('timestamp', ''),
                'provider': data.get('provider', ''),
                'summary': data.get('summary', {}),
                'by_tag': data.get('by_tag', {}),
                'filepath': f,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return jsonify(result)


@app.route('/api/eval/reports/<report_id>')
def get_eval_report(report_id):
    """获取单份评测报告的完整数据"""
    path = os.path.join(REPORTS_DIR, f'{report_id}.json')
    if not os.path.exists(path):
        return jsonify({'error': 'not found'}), 404
    with open(path, 'r', encoding='utf-8') as f:
        return jsonify(json.load(f))


@app.route('/api/eval/reports/<report_id>/trajectory/<case_id>')
def get_eval_trajectory(report_id, case_id):
    """从评测报告中获取某条用例的轨迹"""
    path = os.path.join(REPORTS_DIR, f'{report_id}.json')
    if not os.path.exists(path):
        return jsonify({'error': '报告不存在'}), 404
    with open(path, encoding='utf-8') as f:
        report = json.load(f)
    for result in report.get('results', []):
        if result.get('case_id') == case_id:
            traj_file = result.get('trajectory_file', '')
            if traj_file:
                return get_trajectory(traj_file)
            return jsonify({'error': '该用例无轨迹文件'}), 404
    return jsonify({'error': '未找到该用例'}), 404


@app.route('/api/eval/run', methods=['POST'])
def run_eval():
    """运行评测

    请求体:
        {"provider": "deepseek", "tag": "local"}
    或
        {"provider": "deepseek"}
    """
    data = request.get_json(force=True) or {}
    provider = data.get('provider', os.environ.get('LLM_PROVIDER'))
    tag = data.get('tag', None)

    # 异步？不，先同步执行（小规模）
    from react_agent.eval import EvalRunner
    runner = EvalRunner()
    runner.load_dataset(tag=tag)
    if not runner.cases:
        return jsonify({'error': '没有匹配的测试用例'}), 400
    runner.run_all(provider=provider, progress=False)
    path = runner.save_report()

    return jsonify({
        'report_id': runner.report.get('report_id', ''),
        'summary': runner.summary(),
        'failures': runner.report.get('failures', []),
        'report_path': path,
    })


# ── 系统 API ──

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """立即终止本地 dashboard 进程，不执行 Flask 清理钩子。"""
    os._exit(0)


def kill_old_server(port=5050):
    """启动前杀掉占用端口的旧进程"""
    if sys.platform.startswith('win'):
        # PowerShell 方式
        ps_cmd = (
            f'$p = netstat -ano | Select-String ":{port} "; '
            f'if ($p) {{ $pid = $p.Line.Trim().Split()[-1]; '
            f'  if ($pid -and $pid -ne "0") {{ Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }} }}'
        )
        subprocess.run(['powershell', '-Command', ps_cmd],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    else:
        subprocess.run(['pkill', '-f', f'python.*server.py.*:{port}'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)


if __name__ == '__main__':
    kill_old_server(5050)
    app.run(host='127.0.0.1', port=5050, debug=False, use_reloader=False)
