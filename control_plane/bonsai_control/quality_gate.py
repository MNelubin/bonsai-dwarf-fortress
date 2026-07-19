from __future__ import annotations

import ast
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


RUFF_SELECT = "E4,E7,E9,F,B,SIM,RUF100"
MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::\d+)?: error: (?P<message>.*?)(?:  \[(?P<code>[^]]+)\])?$"
)
MAX_ADDED_PYTHON_LINES = 600
MAX_ADDED_LINES_PER_FILE = 400


def _git_text(repo: Path, ref: str, path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout if result.returncode == 0 else ""


def _candidate_text(repo: Path, candidate_ref: str | None, path: str) -> str:
    if candidate_ref is not None:
        return _git_text(repo, candidate_ref, path)
    candidate = repo / path
    return candidate.read_text(encoding="utf-8", errors="replace") if candidate.is_file() else ""


def _added_lines(base_text: str, candidate_text: str) -> set[int]:
    base_lines = base_text.splitlines()
    candidate_lines = candidate_text.splitlines()
    added: set[int] = set()
    matcher = difflib.SequenceMatcher(a=base_lines, b=candidate_lines, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "insert"}:
            added.update(range(j1 + 1, j2 + 1))
    return added


def _relative_tool_path(repo: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().removeprefix("./")


def _meaningful_body(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _is_placeholder_statement(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return statement.value.value is Ellipsis
    if isinstance(statement, ast.Raise):
        exception = statement.exc
        if isinstance(exception, ast.Call):
            exception = exception.func
        return isinstance(exception, ast.Name) and exception.id == "NotImplementedError"
    return False


def _is_literal_true_assert(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Assert)
        and isinstance(statement.test, ast.Constant)
        and statement.test.value is True
    )


def _ast_diagnostics(path: str, content: str, added_lines: set[int]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return diagnostics

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
            touched = any(node.lineno <= line <= end_line for line in added_lines)
            if not touched:
                continue
            body = _meaningful_body(node.body)
            abstract = any(
                (isinstance(decorator, ast.Name) and decorator.id == "abstractmethod")
                or (isinstance(decorator, ast.Attribute) and decorator.attr == "abstractmethod")
                for decorator in node.decorator_list
            )
            if body and all(_is_placeholder_statement(statement) for statement in body) and not abstract:
                diagnostics.append(
                    {
                        "tool": "anti_slop",
                        "path": path,
                        "line": node.lineno,
                        "code": "SLOP001",
                        "message": f"new function {node.name!r} is only a placeholder",
                    }
                )
            if (
                node.name.startswith("test_")
                and body
                and all(_is_placeholder_statement(statement) or _is_literal_true_assert(statement) for statement in body)
            ):
                diagnostics.append(
                    {
                        "tool": "anti_slop",
                        "path": path,
                        "line": node.lineno,
                        "code": "SLOP002",
                        "message": f"test {node.name!r} has no meaningful assertion",
                    }
                )
        if isinstance(node, ast.ExceptHandler):
            broad = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
            )
            body = _meaningful_body(node.body)
            touched = node.lineno in added_lines or any(statement.lineno in added_lines for statement in body)
            if broad and touched and body and all(isinstance(statement, ast.Pass) for statement in body):
                diagnostics.append(
                    {
                        "tool": "anti_slop",
                        "path": path,
                        "line": node.lineno,
                        "code": "SLOP003",
                        "message": "new broad exception handler silently discards every error",
                    }
                )
    return diagnostics


def evaluate_python_quality(
    repo: Path,
    base_ref: str,
    changed_paths: list[str],
    candidate_ref: str | None = None,
) -> dict[str, Any]:
    """Run differential quality checks and report only issues on authored lines."""
    python_paths: list[str] = []
    added_by_path: dict[str, set[int]] = {}
    candidate_by_path: dict[str, str] = {}
    for path in sorted(set(changed_paths)):
        if not path.endswith(".py"):
            continue
        candidate_text = _candidate_text(repo, candidate_ref, path)
        if not candidate_text:
            continue
        python_paths.append(path)
        candidate_by_path[path] = candidate_text
        added_by_path[path] = _added_lines(_git_text(repo, base_ref, path), candidate_text)

    diagnostics: list[dict[str, Any]] = []
    added_counts = {path: len(lines) for path, lines in added_by_path.items()}
    total_added = sum(added_counts.values())
    if total_added > MAX_ADDED_PYTHON_LINES:
        diagnostics.append(
            {
                "tool": "anti_slop",
                "path": "<diff>",
                "line": 0,
                "code": "SLOP010",
                "message": f"candidate adds {total_added} Python lines; limit is {MAX_ADDED_PYTHON_LINES}",
            }
        )
    for path, count in added_counts.items():
        if count > MAX_ADDED_LINES_PER_FILE:
            diagnostics.append(
                {
                    "tool": "anti_slop",
                    "path": path,
                    "line": 0,
                    "code": "SLOP011",
                    "message": f"candidate adds {count} lines in one Python file; limit is {MAX_ADDED_LINES_PER_FILE}",
                }
            )
        diagnostics.extend(_ast_diagnostics(path, candidate_by_path[path], added_by_path[path]))

    commands: list[dict[str, Any]] = []
    if python_paths:
        ruff = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "--select",
                RUFF_SELECT,
                "--output-format",
                "json",
                *python_paths,
            ],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        commands.append({"name": "ruff", "raw_exit_code": ruff.returncode, "output": ruff.stdout[-16000:]})
        try:
            ruff_items = json.loads(ruff.stdout or "[]")
        except json.JSONDecodeError:
            ruff_items = []
            diagnostics.append(
                {
                    "tool": "ruff",
                    "path": "<tool>",
                    "line": 0,
                    "code": "TOOL001",
                    "message": f"ruff returned invalid JSON: {ruff.stdout[-1000:]}",
                }
            )
        for item in ruff_items:
            path = _relative_tool_path(repo, str(item.get("filename") or ""))
            line = int((item.get("location") or {}).get("row") or 0)
            if line in added_by_path.get(path, set()):
                diagnostics.append(
                    {
                        "tool": "ruff",
                        "path": path,
                        "line": line,
                        "code": str(item.get("code") or "RUFF"),
                        "message": str(item.get("message") or "ruff violation"),
                    }
                )

        mypy = subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--ignore-missing-imports",
                "--follow-imports=skip",
                "--allow-untyped-defs",
                "--check-untyped-defs",
                "--show-error-codes",
                "--no-error-summary",
                "--hide-error-context",
                "--no-color-output",
                "--no-pretty",
                *python_paths,
            ],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        commands.append({"name": "mypy", "raw_exit_code": mypy.returncode, "output": mypy.stdout[-16000:]})
        parsed_mypy_errors = 0
        for raw_line in mypy.stdout.splitlines():
            match = MYPY_ERROR.match(raw_line)
            if match is None:
                continue
            parsed_mypy_errors += 1
            path = _relative_tool_path(repo, match.group("path"))
            line = int(match.group("line"))
            if line in added_by_path.get(path, set()):
                diagnostics.append(
                    {
                        "tool": "mypy",
                        "path": path,
                        "line": line,
                        "code": match.group("code") or "mypy",
                        "message": match.group("message"),
                    }
                )
        if mypy.returncode not in {0, 1} or (mypy.returncode != 0 and parsed_mypy_errors == 0):
            diagnostics.append(
                {
                    "tool": "mypy",
                    "path": "<tool>",
                    "line": 0,
                    "code": "TOOL002",
                    "message": f"mypy could not run: {mypy.stdout[-1000:]}",
                }
            )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.get("tool"),
            diagnostic.get("path"),
            diagnostic.get("line"),
            diagnostic.get("code"),
            diagnostic.get("message"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(diagnostic)
    return {
        "ok": not unique,
        "diagnostics": unique,
        "python_paths": python_paths,
        "added_lines": added_counts,
        "commands": commands,
        "policy": {
            "ruff_select": RUFF_SELECT,
            "max_added_python_lines": MAX_ADDED_PYTHON_LINES,
            "max_added_lines_per_file": MAX_ADDED_LINES_PER_FILE,
            "mypy_scope": "errors on added or modified lines",
        },
    }
