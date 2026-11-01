"""命令注册守卫。

AstrBot 的 handler 过滤器是 **AND** 关系（见 waking_check/stage.py 的注释），
同一函数叠多个 @filter.command 会让它永远不匹配。
这个测试直接检查源码：img_command 只能有一个 command 装饰器，别名要走 alias。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_main_tree() -> ast.Module:
    return ast.parse((REPO / "main.py").read_text(encoding="utf-8"))


class TestCommandRegistration(unittest.TestCase):
    def test_single_command_decorator(self) -> None:
        tree = load_main_tree()
        target = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "img_command":
                target = node
                break
        self.assertIsNotNone(target, "找不到 img_command")

        command_decorators = []
        for decorator in target.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            if call is None:
                continue
            func = call.func
            name = getattr(func, "attr", "") or getattr(func, "id", "")
            if name == "command":
                command_decorators.append(call)

        self.assertEqual(
            len(command_decorators),
            1,
            "img_command 上有多个 @filter.command：AstrBot 过滤器是 AND 关系，会永远不匹配",
        )

        call = command_decorators[0]
        alias_values: set[str] = set()
        for keyword in call.keywords:
            if keyword.arg == "alias" and isinstance(keyword.value, ast.Set):
                for element in keyword.value.elts:
                    if isinstance(element, ast.Constant):
                        alias_values.add(str(element.value))

        self.assertIn("draw", alias_values, "/draw 别名应当通过 alias 注册")
        self.assertIn("画图", alias_values, "/画图 别名应当通过 alias 注册")


if __name__ == "__main__":
    unittest.main()
