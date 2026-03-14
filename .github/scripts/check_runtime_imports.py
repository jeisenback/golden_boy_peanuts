"""
check_runtime_imports.py

AST-based scanner for banned runtime imports in src/.
Enforces ESOD architectural rule: langchain.* and langgraph.* must never
appear as runtime imports in src/. Exits with code 1 if any are found.

Usage:
    python .github/scripts/check_runtime_imports.py

Returns:
    0 — no banned imports found
    1 — one or more banned imports found (details printed to stdout)
"""

import ast
import logging
import pathlib
import sys

BANNED: list[str] = ["langchain", "langgraph"]
SRC_ROOT = pathlib.Path("src")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)


def scan_file(path: pathlib.Path) -> list[str]:
    """
    Parse a single Python file and return a list of violation strings.

    Args:
        path: Path to the .py file to scan.

    Returns:
        List of human-readable violation strings. Empty if no violations.
    """
    violations: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        violations.append(f"PARSE ERROR: {path}: {exc}")
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name or ""
                if any(module_name == b or module_name.startswith(f"{b}.") for b in BANNED):
                    violations.append(f"FAIL: {path}:{node.lineno} — `import {module_name}`")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if any(module_name == b or module_name.startswith(f"{b}.") for b in BANNED):
                violations.append(f"FAIL: {path}:{node.lineno} — `from {module_name} import ...`")
    return violations


def main() -> int:
    """
    Scan all .py files under src/ and report violations.

    Returns:
        Exit code: 0 = clean, 1 = violations found.
    """
    if not SRC_ROOT.exists():
        logger.error("Source root '%s' not found. Run from repository root.", SRC_ROOT)
        return 1

    all_violations: list[str] = []
    file_count = 0
    for path in sorted(SRC_ROOT.rglob("*.py")):
        file_count += 1
        all_violations.extend(scan_file(path))

    if all_violations:
        logger.error("Runtime import check FAILED. Banned imports found in src/:")
        for v in all_violations:
            logger.error("%s", v)
        logger.error(
            "%d violation(s). Remove langchain.* / langgraph.* imports from src/ before pushing.",
            len(all_violations),
        )
        return 1

    logger.info("Runtime import check PASSED. Scanned %d file(s).", file_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
