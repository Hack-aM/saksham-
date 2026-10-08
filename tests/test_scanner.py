"""Unit tests for rule-based project scanner (scanner.py).

Verifies language, framework, entry point, port, and dependency detection
without importing or executing any untrusted code.
"""

from pathlib import Path
import pytest
from scanner import scan_project
from schemas import ScanResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_scanner_on_vulnerable_demo_app() -> None:
    """Verify scanner on vulnerable-demo-app fixture."""
    project_path = FIXTURES_DIR / "vulnerable-demo-app"
    result = scan_project(project_path)

    assert isinstance(result, ScanResult)
    assert result.supported is True
    assert result.language == "Python"
    assert result.framework == "FastAPI"
    assert result.stack == "Python / FastAPI"
    assert result.entry_point == "main.py"
    assert result.port == 8000
    assert "fastapi" in result.dependencies
    assert "uvicorn" in result.dependencies


def test_scanner_on_clean_app() -> None:
    """Verify scanner on clean-app fixture."""
    project_path = FIXTURES_DIR / "clean-app"
    result = scan_project(project_path)

    assert isinstance(result, ScanResult)
    assert result.supported is True
    assert result.language == "Python"
    assert result.framework == "FastAPI"
    assert result.stack == "Python / FastAPI"
    assert result.entry_point == "main.py"
    assert result.port == 8000
    assert "fastapi" in result.dependencies


def test_scanner_on_node_react_project(tmp_path: Path) -> None:
    """Verify scanner flags Node.js / React project as unsupported in MVP with a clear message."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(
        """{
            "name": "sample-react-app",
            "version": "1.0.0",
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            }
        }""",
        encoding="utf-8",
    )

    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.language == "JavaScript/TypeScript"
    assert result.framework == "React"
    assert "Node.js" in result.stack
    assert "react" in result.dependencies
    assert "Node.js / React projects are not supported in MVP" in (result.message or "")


def test_scanner_on_node_express_project(tmp_path: Path) -> None:
    """Verify scanner flags Node.js / Express project as unsupported in MVP."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(
        """{
            "name": "sample-express-api",
            "version": "1.0.0",
            "dependencies": {
                "express": "^4.18.2"
            }
        }""",
        encoding="utf-8",
    )

    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.framework == "Express"
    assert "Node.js" in result.stack


def test_scanner_on_empty_project(tmp_path: Path) -> None:
    """Verify scanner returns unknown stack for empty directory without crashing."""
    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.stack == "unknown"
    assert result.language == "unknown"
    assert result.framework == "unknown"
    assert result.entry_point is None
    assert "No recognizable Python or FastAPI" in (result.message or "")


def test_scanner_on_python_syntax_error(tmp_path: Path) -> None:
    """Verify scanner handles syntax errors in main.py via regex fallback without crashing."""
    broken_main = tmp_path / "main.py"
    broken_main.write_text(
        """from fastapi import FastAPI
app = FastAPI()

def broken_syntax(
    # Unclosed parentheses and invalid syntax
    print "invalid python 3 syntax"
""",
        encoding="utf-8",
    )
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("fastapi==0.110.0\nuvicorn==0.28.0", encoding="utf-8")

    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is True
    assert result.framework == "FastAPI"
    assert result.entry_point == "main.py"
    assert result.port == 8000


def test_scanner_on_generic_python_project(tmp_path: Path) -> None:
    """Verify scanner flags generic Python project without FastAPI as unsupported."""
    script = tmp_path / "script.py"
    script.write_text("print('just a script')\n", encoding="utf-8")
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("requests==2.31.0\n", encoding="utf-8")

    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.language == "Python"
    assert result.framework == "Generic"
    assert "Only FastAPI is supported in MVP" in (result.message or "")


def test_scanner_on_custom_port_in_code(tmp_path: Path) -> None:
    """Verify scanner extracts custom port from os.getenv or uvicorn configuration."""
    main_py = tmp_path / "main.py"
    main_py.write_text(
        """import os
import uvicorn
from fastapi import FastAPI

app = FastAPI()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9090))
    uvicorn.run(app, host="0.0.0.0", port=port)
""",
        encoding="utf-8",
    )
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("fastapi\nuvicorn\n", encoding="utf-8")

    result = scan_project(tmp_path)

    assert isinstance(result, ScanResult)
    assert result.supported is True
    assert result.framework == "FastAPI"
    assert result.port == 9090


def test_scanner_on_nonexistent_directory() -> None:
    """Verify scanner returns unknown stack when target path does not exist."""
    missing_dir = Path("nonexistent_directory_for_test_12345")
    result = scan_project(missing_dir)

    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.stack == "unknown"
    assert "Project directory not found" in (result.message or "")


def test_scanner_skips_oversized_files(tmp_path: Path) -> None:
    """Verify scanner skips files exceeding max_scan_file_size_bytes."""
    from config import Settings
    custom_settings = Settings(
        gemini_api_key="test",
        gemini_model="gemini-2.5-flash",
        github_token="test",
        render_api_key="test",
    )
    custom_settings.max_scan_file_size_bytes = 50  # Very low 50 bytes limit

    main_py = tmp_path / "main.py"
    # Write file larger than 50 bytes (78 bytes)
    main_py.write_text("from fastapi import FastAPI\napp = FastAPI()\n# Some long comment to exceed limit", encoding="utf-8")

    # Scanner should skip reading main.py due to size limit, returning Generic Python without crash
    result = scan_project(tmp_path, settings=custom_settings)
    assert isinstance(result, ScanResult)
    assert result.supported is False
    assert result.framework == "Generic"


def test_scanner_handles_recursion_and_memory_errors(tmp_path: Path, monkeypatch) -> None:
    """Verify scanner handles RecursionError and MemoryError during AST parsing gracefully."""
    import ast

    def mock_ast_parse(*args, **kwargs):
        raise RecursionError("Simulated deep recursion limit exceeded")

    monkeypatch.setattr(ast, "parse", mock_ast_parse)

    main_py = tmp_path / "main.py"
    main_py.write_text("from fastapi import FastAPI\napp = FastAPI()", encoding="utf-8")
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("fastapi\nuvicorn", encoding="utf-8")

    result = scan_project(tmp_path)
    assert isinstance(result, ScanResult)
    # Should fall back to regex without crashing and still detect FastAPI
    assert result.supported is True
    assert result.framework == "FastAPI"

