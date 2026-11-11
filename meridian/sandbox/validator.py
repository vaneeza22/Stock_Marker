"""Static pre-flight for model-written code. This is defence in depth, NOT the security boundary:
the boundary is the OS process (rlimits, no network, scrubbed env) or the Docker container."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List

ALLOWED_IMPORTS = {"math", "statistics", "json", "datetime", "collections", "itertools", "functools", "re",
                   "decimal", "fractions", "random", "numpy", "pandas", "typing", "dataclasses"}
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "input", "breakpoint", "help", "exit", "quit", "globals",
                 "locals", "vars", "getattr", "setattr", "delattr", "__import__", "memoryview"}
BLOCKED_ATTRS = {"to_csv", "to_pickle", "to_parquet", "to_excel", "to_hdf", "to_feather", "to_sql", "to_clipboard",
                 "to_xml", "to_stata", "to_orc", "tofile", "dump", "load", "loadtxt", "genfromtxt", "savetxt",
                 "save", "savez", "memmap", "fromfile", "eval", "query", "system", "popen"}


@dataclass
class Violation:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def validate(code: str, max_chars: int = 20000) -> List[Violation]:
    if len(code) > max_chars:
        return [Violation(1, f"code too long ({len(code)} > {max_chars} chars)")]
    try:
        tree = ast.parse(code, filename="<analysis>")
    except SyntaxError as e:
        return [Violation(e.lineno or 1, f"SyntaxError: {e.msg}")]
    out: List[Violation] = []
    for node in ast.walk(tree):
        ln = getattr(node, "lineno", 1)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    out.append(Violation(ln, f"import of '{a.name}' is not allowed (allowed: {sorted(ALLOWED_IMPORTS)})"))
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                out.append(Violation(ln, f"import from '{node.module}' is not allowed"))
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            out.append(Violation(ln, f"use of '{node.id}' is not allowed"))
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                out.append(Violation(ln, f"access to private/dunder attribute '{node.attr}' is not allowed"))
            elif node.attr in BLOCKED_ATTRS or node.attr.startswith("read_"):
                out.append(Violation(ln, f"attribute '.{node.attr}' is blocked (file/eval access)"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            out.append(Violation(ln, "string containing '__' is not allowed"))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.append(Violation(ln, "global/nonlocal not allowed"))
    return out
