"""检查企业只读连接器配置，不打印 Token 或其他 Secret。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.eval.connectors import ConnectorConfig, load_env_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=("jira", "gitlab", "zendesk", "servicenow", "apm"))
    args = parser.parse_args()
    load_env_file(ROOT / ".env")
    prefix = args.source.upper()
    try:
        config = ConnectorConfig.from_env(prefix)
    except ValueError as exc:
        print(f"{prefix}: 配置不完整：{exc}")
        return 2

    print(
        f"{prefix}: 配置存在；base_url={config.base_url} "
        f"auth_header={config.auth_header} auth_scheme={config.auth_scheme or '<empty>'} "
        f"token_set={bool(os.environ.get(f'{prefix}_READONLY_TOKEN', '').strip())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
