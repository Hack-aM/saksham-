"""Unit tests for Deterministic Template Generation in fixer.py (T18).

All templates are deterministic, non-LLM, contain no raw secrets, and generate
valid Patch proposals without modifying disk.
"""

from pathlib import Path
import pytest

from fixer import (
    FixerError,
    propose_missing_file_patches,
    render_template,
    validate_patch_safety,
)
from schemas import PatchStatusEnum

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def test_render_all_templates_deterministic_and_no_secrets():
    """Verify that all template files render deterministically without real secrets."""
    templates = [
        "Dockerfile.template",
        "gitignore.template",
        "ci.yml.template",
        "README.md.template",
        "env_example.template",
    ]

    for t_name in templates:
        rendered1 = render_template(t_name)
        rendered2 = render_template(t_name)
        assert rendered1 == rendered2
        assert len(rendered1) > 0

        # Assert no real secret patterns in template files
        assert "ghp_" not in rendered1
        assert "AIzaSy" not in rendered1
        assert "rnd_" not in rendered1
        assert "sk-proj-" not in rendered1


def test_render_template_variable_substitution():
    """Verify placeholder replacement in README template."""
    context = {"project_name": "MyFastAPIDemo", "entry_point": "app"}
    rendered = render_template("README.md.template", context=context)

    assert "# MyFastAPIDemo" in rendered
    assert "uvicorn app:app" in rendered
    assert "{{ project_name }}" not in rendered


def test_render_nonexistent_template_raises_error():
    """Verify that requesting a missing template raises FixerError."""
    with pytest.raises(FixerError) as exc_info:
        render_template("nonexistent.template")
    assert "not found" in str(exc_info.value).lower()


def test_propose_missing_file_patches_for_empty_project(tmp_path):
    """Verify that an empty project directory receives proposals for all standard starter files."""
    patches = propose_missing_file_patches(
        tmp_path,
        project_name="DemoApp",
        entry_point="main.py",
    )

    files = [p.file for p in patches]
    assert ".gitignore" in files
    assert ".env.example" in files
    assert "Dockerfile" in files
    assert ".github/workflows/ci.yml" in files
    assert "README.md" in files

    for p in patches:
        assert p.old == ""
        assert len(p.new) > 0
        assert p.status == PatchStatusEnum.SUGGESTED
        # Verify compatibility with T17 safety validator
        validate_patch_safety(p, tmp_path)

    # Verify that T18 proposals are strictly in-memory and did NOT create files on disk
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / "Dockerfile").exists()


def test_propose_missing_file_patches_skips_existing_files(tmp_path):
    """Verify that existing starter files are not proposed again."""
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n", encoding="utf-8")

    patches = propose_missing_file_patches(tmp_path)
    files = [p.file for p in patches]

    assert ".gitignore" not in files
    assert "Dockerfile" not in files
    assert ".env.example" in files
    assert ".github/workflows/ci.yml" in files
    assert "README.md" in files


def test_repeated_generation_is_strictly_identical(tmp_path):
    """Verify that calling propose_missing_file_patches multiple times produces identical content."""
    patches_run1 = propose_missing_file_patches(tmp_path, project_name="StableApp")
    patches_run2 = propose_missing_file_patches(tmp_path, project_name="StableApp")

    assert len(patches_run1) == len(patches_run2)
    for p1, p2 in zip(patches_run1, patches_run2):
        assert p1.file == p2.file
        assert p1.old == p2.old
        assert p1.new == p2.new
        assert p1.reason == p2.reason
        assert p1.status == p2.status


def test_templates_contain_no_dangerous_command_injections():
    """Verify that no template introduces dangerous shell execution patterns."""
    templates = [
        "Dockerfile.template",
        "gitignore.template",
        "ci.yml.template",
        "README.md.template",
        "env_example.template",
    ]

    for t_name in templates:
        rendered = render_template(t_name)
        assert "os.system(" not in rendered
        assert "rm -rf /" not in rendered
        assert "format C:" not in rendered
