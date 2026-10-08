"""Saksham Project Scanner Module.

Rule-based static project detection for language, framework, entry point, port,
and dependencies.
Security: Files are read strictly as static text or via Python's AST parser.
Uploaded code is NEVER imported or executed.
"""

import ast
import json
import re
from pathlib import Path
from typing import List, Optional, Set, Tuple
from config import Settings, get_settings
from schemas import ScanResult

COMMON_ENTRY_POINTS = ["main.py", "app.py", "server.py", "api.py", "index.py"]


def _extract_dependencies_from_requirements(req_path: Path, settings: Optional[Settings] = None) -> List[str]:
    """Parse dependency names from requirements.txt without running pip."""
    deps: List[str] = []
    if not req_path.is_file():
        return deps

    cfg = settings or get_settings()
    try:
        if req_path.stat().st_size > cfg.max_scan_file_size_bytes:
            return deps
        content = req_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Extract package name before ==, >=, <=, ~=, <, >, ;
            pkg_match = re.match(r"^([a-zA-Z0-9_\-\.]+)", line)
            if pkg_match:
                deps.append(pkg_match.group(1).lower())
    except Exception:
        pass
    return deps


def _safe_ast_or_regex_search(py_file: Path, settings: Optional[Settings] = None) -> Tuple[bool, Optional[int]]:
    """Inspect a Python file for FastAPI usage and port configurations.

    Uses ast.parse with regex fallback if the file contains syntax errors,
    recursion errors, or memory limits. Skips files exceeding max_scan_file_size_bytes.
    """
    has_fastapi = False
    detected_port: Optional[int] = None
    cfg = settings or get_settings()

    try:
        if py_file.stat().st_size > cfg.max_scan_file_size_bytes:
            # Skip oversized files to prevent memory exhaustion
            return False, None
        content = py_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False, None

    # 1. Try structured AST inspection
    try:
        tree = ast.parse(content, filename=py_file.name)
        for node in ast.walk(tree):
            # Check for "import fastapi" or "from fastapi import ..."
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                        has_fastapi = True
            elif isinstance(node, ast.ImportFrom):
                if node.module == "fastapi" or (node.module and node.module.startswith("fastapi.")):
                    has_fastapi = True
            # Check for FastAPI() instantiation
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "FastAPI":
                    has_fastapi = True
                elif isinstance(func, ast.Attribute) and func.attr == "FastAPI":
                    has_fastapi = True
    except (SyntaxError, RecursionError, MemoryError):
        # Fallback to regex text search for syntax, recursion, or memory errors
        if re.search(r"\b(import\s+fastapi|from\s+fastapi\s+import|FastAPI\s*\()\b", content):
            has_fastapi = True

    # 2. Extract port from AST/Text
    # Look for patterns like port=8000, os.getenv("PORT", "8000"), os.getenv("PORT", 8000), PORT = 8000
    port_match = re.search(r"port\s*=\s*([0-9]{2,5})", content, re.IGNORECASE)
    if port_match:
        try:
            detected_port = int(port_match.group(1))
        except ValueError:
            pass

    if not detected_port:
        port_env_match = re.search(r"""os\.(?:getenv|environ\.get)\(\s*['"]PORT['"]\s*,\s*['"]?([0-9]{2,5})['"]?\s*\)""", content)
        if port_env_match:
            try:
                detected_port = int(port_env_match.group(1))
            except ValueError:
                pass

    if not detected_port:
        port_const_match = re.search(r"""\bPORT\s*=\s*int\(\s*os\.(?:getenv|environ\.get)\([^)]*['"]?([0-9]{2,5})['"]?\s*\)""", content)
        if port_const_match:
            try:
                detected_port = int(port_const_match.group(1))
            except ValueError:
                pass

    if not detected_port:
        port_var_match = re.search(r"""\bPORT\s*=\s*([0-9]{2,5})\b""", content)
        if port_var_match:
            try:
                detected_port = int(port_var_match.group(1))
            except ValueError:
                pass

    return has_fastapi, detected_port


def scan_project(project_dir: Path, settings: Optional[Settings] = None) -> ScanResult:
    """Scan and detect project language, framework, entry point, and port.

    Args:
        project_dir: Path to the root of the extracted project.
        settings: Application settings configuration.

    Returns:
        ScanResult: Pydantic model with detection outcome.
    """
    if not project_dir.is_dir():
        return ScanResult(
            stack="unknown",
            language="unknown",
            framework="unknown",
            supported=False,
            message=f"Project directory not found: {project_dir}",
        )

    all_files = list(project_dir.rglob("*"))
    file_names = {f.name for f in all_files if f.is_file()}

    # 1. Node.js detection (package.json)
    package_json = project_dir / "package.json"
    if package_json.is_file():
        framework_name = "Node.js"
        deps: List[str] = []
        try:
            data = json.loads(package_json.read_text(encoding="utf-8", errors="ignore"))
            all_pkg_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            deps = list(all_pkg_deps.keys())
            if "react" in all_pkg_deps:
                framework_name = "React"
            elif "express" in all_pkg_deps:
                framework_name = "Express"
            elif "next" in all_pkg_deps:
                framework_name = "Next.js"
        except Exception:
            pass

        return ScanResult(
            stack=f"Node.js / {framework_name}",
            language="JavaScript/TypeScript",
            framework=framework_name,
            entry_point="package.json",
            port=3000,
            dependencies=deps,
            supported=False,
            message="Node.js / React projects are not supported in MVP. Only Python / FastAPI projects are currently supported.",
        )

    # 2. Python / FastAPI detection
    req_file = project_dir / "requirements.txt"
    py_files = [f for f in all_files if f.is_file() and f.suffix == ".py"]
    has_python = req_file.is_file() or bool(py_files)

    if has_python:
        dependencies = _extract_dependencies_from_requirements(req_file, settings=settings) if req_file.is_file() else []
        has_fastapi_dep = "fastapi" in dependencies

        # Find entry point and inspect for FastAPI
        detected_entry_point: Optional[str] = None
        has_fastapi_code = False
        detected_port: Optional[int] = None

        # Check common entry points first
        for name in COMMON_ENTRY_POINTS:
            candidate = project_dir / name
            if candidate.is_file():
                detected_entry_point = name
                is_fastapi, port = _safe_ast_or_regex_search(candidate, settings=settings)
                if is_fastapi:
                    has_fastapi_code = True
                if port:
                    detected_port = port
                break

        # If not found in common entry points, inspect other python files
        if not detected_entry_point and py_files:
            for py_file in py_files:
                is_fastapi, port = _safe_ast_or_regex_search(py_file, settings=settings)
                if is_fastapi:
                    has_fastapi_code = True
                    detected_entry_point = str(py_file.relative_to(project_dir)).replace("\\", "/")
                if port and not detected_port:
                    detected_port = port

        # Check config.py or settings.py for port if not yet found
        for cfg_name in ["config.py", "settings.py"]:
            cfg_file = project_dir / cfg_name
            if cfg_file.is_file():
                _, port = _safe_ast_or_regex_search(cfg_file, settings=settings)
                if port and not detected_port:
                    detected_port = port

        if has_fastapi_dep or has_fastapi_code:
            final_port = detected_port or 8000
            return ScanResult(
                stack="Python / FastAPI",
                language="Python",
                framework="FastAPI",
                entry_point=detected_entry_point or "main.py",
                port=final_port,
                dependencies=dependencies,
                supported=True,
                message="Successfully detected Python / FastAPI application.",
            )

        # Python project but not FastAPI
        return ScanResult(
            stack="Python (Generic)",
            language="Python",
            framework="Generic",
            entry_point=detected_entry_point or (str(py_files[0].relative_to(project_dir)).replace("\\", "/") if py_files else None),
            port=detected_port or 8000,
            dependencies=dependencies,
            supported=False,
            message="Python project detected, but FastAPI framework was not found. Only FastAPI is supported in MVP.",
        )

    # 3. EXTENSION POINT: LLM fallback for unknown project detection (T15)
    # When rules cannot classify the project, an LLM tool-calling agent will inspect file tree in T15.

    return ScanResult(
        stack="unknown",
        language="unknown",
        framework="unknown",
        entry_point=None,
        port=8000,
        dependencies=[],
        supported=False,
        message="No recognizable Python or FastAPI configuration files found in project.",
    )
