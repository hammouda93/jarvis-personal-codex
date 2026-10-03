"""Static inventory: no runtime imports and no reading of secret values."""
from __future__ import annotations

import ast
import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = []
    for path in sorted((root / "jarvis_agent").glob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        modules.append({
            "path": path.relative_to(root).as_posix(),
            "lines": len(source.splitlines()),
            "classes": [n.name for n in tree.body if isinstance(n, ast.ClassDef)],
            "functions": [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
            "imports": sorted({
                ("." * n.level) + (n.module or "")
                for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            } | {
                alias.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                for alias in n.names
            }),
        })
    tests = {}
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tests[path.name] = sum(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_") for n in ast.walk(tree)
        )
    output = root / "docs" / "PERSONAL_AI_AGENT_ARCHITECTURE.json"
    output.write_text(json.dumps({
        "method": "AST only; live authority requires code-path inspection",
        "modules": modules,
        "test_methods": tests,
        "total_test_methods": sum(tests.values()),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(modules)} modules; {sum(tests.values())} test methods")


if __name__ == "__main__":
    main()
