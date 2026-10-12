"""Smoke tests verifying that all core Saksham modules import cleanly without error."""

import importlib
import pytest

MODULES = [
    "main",
    "config",
    "schemas",
    "db",
    "upload",
    "scanner",
    "audit",
    "fixer",
    "llm",
    "github_push",
    "deployer",
    "auth",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Ensure that the module can be imported without raising any exceptions."""
    mod = importlib.import_module(module_name)
    assert mod is not None
