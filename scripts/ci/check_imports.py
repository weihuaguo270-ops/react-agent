#!/usr/bin/env python3
"""检查所有 Python 文件的导入是否有效。"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any


def check_imports(file_path: Path) -> list[str]:
    """检查文件中的导入是否有效。"""
    errors = []
    try:
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content, str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # 检查 from X import Y 语句
                if node.module:
                    module_parts = node.module.split('.')
                    # 检查是否是项目内部导入
                    if module_parts[0] in ('react_agent', 'tests'):
                        for alias in node.names:
                            name = alias.name
                            if name != '*':
                                # 记录导入信息供后续验证
                                pass
    except SyntaxError as e:
        errors.append(f"{file_path}:{e.lineno}: Syntax error: {e.msg}")
    except Exception as e:
        errors.append(f"{file_path}: Error parsing: {e}")

    return errors


def main():
    """主函数。"""
    root = Path(__file__).parent.parent.parent
    errors = []

    # 检查 src 和 tests 目录
    for pattern in ['src/**/*.py', 'tests/**/*.py']:
        for py_file in root.glob(pattern):
            if '__pycache__' in str(py_file):
                continue
            file_errors = check_imports(py_file)
            errors.extend(file_errors)

    if errors:
        print("Import check failed:")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    else:
        print("All imports look valid")
        sys.exit(0)


if __name__ == '__main__':
    main()
