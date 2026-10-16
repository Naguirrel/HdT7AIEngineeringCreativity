"""Secrets stay out of Git and Docker; evaluations are pinned to one case at a time."""

import ast
import fnmatch
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _dockerignored(path: str) -> bool:
    """Docker .dockerignore semantics: last matching rule wins, '!' re-includes."""
    ignored = False
    for raw in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negate = rule.startswith("!")
        pattern = rule[1:] if negate else rule
        pattern = pattern.rstrip("/")
        parts = path.split("/")
        prefixes = ["/".join(parts[: index + 1]) for index in range(len(parts))]
        if any(fnmatch.fnmatch(prefix, pattern) for prefix in prefixes) or fnmatch.fnmatch(parts[-1], pattern):
            ignored = not negate
    return ignored


@pytest.mark.parametrize("path", [
    ".env", ".env.local", ".env.production", "node_modules/promptfoo/index.js", ".venv/Lib/site.py",
    ".venv/promptfoo-state/promptfoo.db", ".promptfoo/cache.db", "reports/promptfoo-results.json",
    "src/__pycache__/config.cpython-312.pyc", ".pytest_cache/v/x", ".vscode/settings.json",
    "logs/debug.log", "promptfoo-error.log",
])
def test_sensitive_and_local_files_are_excluded_from_docker_context(path):
    assert _dockerignored(path)


@pytest.mark.parametrize("path", [".env.example", "src/config.py", "requirements.txt", "evals/provider.py"])
def test_runtime_files_and_env_example_stay_in_docker_context(path):
    assert not _dockerignored(path)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_env_is_ignored_and_not_tracked_by_git():
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, check=False)
    assert ignored.returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"], cwd=ROOT, capture_output=True, check=False
    )
    assert tracked.returncode != 0


def test_promptfoo_concurrency_is_pinned_in_config_and_scripts():
    config = (ROOT / "evals" / "promptfooconfig.yaml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^evaluateOptions:\n\s+maxConcurrency: 1\s*$", config)
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    for name in ("eval", "eval:report"):
        assert "--max-concurrency 1" in scripts[name]


def test_direct_imports_are_declared_and_pinned():
    requirements = {
        line.split("==")[0].strip().lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith("#")
    }
    distributions = {"agents": "openai-agents", "openai": "openai", "pydantic": "pydantic",
                     "requests": "requests", "pytest": "pytest", "requests_mock": "requests-mock"}
    imported = set()
    for folder in ("src", "evals", "scripts", "tests"):
        for file in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imported.add(node.module.split(".")[0])
    third_party = imported & distributions.keys()
    assert {distributions[name] for name in third_party} <= requirements
    # zoneinfo needs tzdata on Windows; it must stay declared.
    assert "tzdata" in requirements
