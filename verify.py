#!/usr/bin/env python3
"""Pre-deploy verification for the autochecker monorepo.

Run: python verify.py
All checks must pass before deploying.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PASSED = 0
FAILED = 0


def check(name: str):
    """Decorator that registers a check function."""
    def decorator(fn):
        fn._check_name = name
        return fn
    return decorator


def run_checks():
    global PASSED, FAILED
    checks = [v for v in globals().values() if callable(v) and hasattr(v, "_check_name")]
    for fn in checks:
        try:
            fn()
            PASSED += 1
            print(f"  PASS  {fn._check_name}")
        except Exception as e:
            FAILED += 1
            print(f"  FAIL  {fn._check_name}: {e}")


# ---------------------------------------------------------------------------
# Structure checks
# ---------------------------------------------------------------------------

@check("autochecker package exists")
def _pkg():
    assert (ROOT / "autochecker" / "__init__.py").exists()
    assert (ROOT / "autochecker" / "__main__.py").exists()
    assert (ROOT / "autochecker" / "cli.py").exists()
    assert (ROOT / "autochecker" / "engine.py").exists()

@check("bot package exists")
def _bot():
    assert (ROOT / "bot" / "__init__.py").exists()
    assert (ROOT / "bot" / "config.py").exists()
    assert (ROOT / "bot" / "runner.py").exists()
    assert (ROOT / "bot" / "database.py").exists()
    for h in ("start", "register", "labs", "check"):
        assert (ROOT / "bot" / "handlers" / f"{h}.py").exists(), f"missing bot/handlers/{h}.py"

@check("dashboard package exists")
def _dash():
    assert (ROOT / "dashboard" / "app.py").exists()
    for t in ("index.html", "login.html", "student.html"):
        assert (ROOT / "dashboard" / "templates" / t).exists(), f"missing dashboard/templates/{t}"

@check("specs exist")
def _specs():
    assert (ROOT / "specs" / "lab-01.yaml").exists()
    assert (ROOT / "specs" / "lab-02.yaml").exists()

@check("entry points exist")
def _entry():
    assert (ROOT / "main.py").exists()
    assert (ROOT / "main_bot.py").exists()

@check("deploy files exist")
def _deploy():
    assert (ROOT / "deploy" / "Dockerfile").exists()
    assert (ROOT / "deploy" / "docker-compose.yml").exists()
    assert (ROOT / "deploy" / "update.sh").exists()

@check("requirements.txt exists")
def _reqs():
    text = (ROOT / "requirements.txt").read_text()
    for pkg in ("typer", "aiogram", "fastapi", "aiosqlite", "pyyaml"):
        assert pkg in text, f"missing {pkg} in requirements.txt"


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------

@check("import autochecker")
def _import_ac():
    mod = importlib.import_module("autochecker")
    assert hasattr(mod, "check_student")
    assert hasattr(mod, "StudentCheckResult")
    assert hasattr(mod, "ROOT_DIR")
    assert hasattr(mod, "SPECS_DIR")
    assert hasattr(mod, "RESULTS_DIR")

@check("import autochecker.cli")
def _import_cli():
    mod = importlib.import_module("autochecker.cli")
    assert hasattr(mod, "app")
    assert hasattr(mod, "LAB_CONFIG")
    assert len(mod.LAB_CONFIG) >= 2

@check("import autochecker.engine")
def _import_engine():
    importlib.import_module("autochecker.engine")

@check("import autochecker.spec")
def _import_spec():
    importlib.import_module("autochecker.spec")

@check("import autochecker.reporter")
def _import_reporter():
    importlib.import_module("autochecker.reporter")

@check("import autochecker.batch_processor")
def _import_batch():
    importlib.import_module("autochecker.batch_processor")


# ---------------------------------------------------------------------------
# Path resolution checks
# ---------------------------------------------------------------------------

@check("ROOT_DIR resolves to repo root")
def _root_dir():
    from autochecker import ROOT_DIR
    assert ROOT_DIR == ROOT, f"expected {ROOT}, got {ROOT_DIR}"

@check("SPECS_DIR points to existing specs/")
def _specs_dir():
    from autochecker import SPECS_DIR
    assert SPECS_DIR.exists(), f"{SPECS_DIR} does not exist"
    assert (SPECS_DIR / "lab-01.yaml").exists()

@check("bot config paths resolve correctly")
def _bot_paths():
    # Can't import bot.config without BOT_TOKEN, so check the file directly
    config_src = (ROOT / "bot" / "config.py").read_text()
    assert "AUTOCHECKER_DIR" not in config_src, "bot/config.py still references AUTOCHECKER_DIR"
    assert "AUTOCHECKER_SCRIPT" not in config_src, "bot/config.py still references AUTOCHECKER_SCRIPT"
    assert 'BASE_DIR = Path(__file__).resolve().parent.parent' in config_src

@check("dashboard paths resolve correctly")
def _dash_paths():
    src = (ROOT / "dashboard" / "app.py").read_text()
    assert "AUTOCHECKER_DIR" not in src, "dashboard/app.py still references AUTOCHECKER_DIR"


# ---------------------------------------------------------------------------
# No stale references
# ---------------------------------------------------------------------------

@check("no subprocess calls in bot/runner.py")
def _no_subprocess():
    src = (ROOT / "bot" / "runner.py").read_text()
    assert "subprocess" not in src, "bot/runner.py still uses subprocess"
    assert "create_subprocess_exec" not in src
    assert "from autochecker import check_student" in src

@check("no AUTOCHECKER_DIR references in bot/")
def _no_old_paths_bot():
    for f in (ROOT / "bot").rglob("*.py"):
        src = f.read_text()
        assert "AUTOCHECKER_DIR" not in src, f"{f} still references AUTOCHECKER_DIR"
        assert "AUTOCHECKER_SCRIPT" not in src, f"{f} still references AUTOCHECKER_SCRIPT"

@check("no AUTOCHECKER_DIR references in dashboard/")
def _no_old_paths_dash():
    for f in (ROOT / "dashboard").rglob("*.py"):
        src = f.read_text()
        assert "AUTOCHECKER_DIR" not in src, f"{f} still references AUTOCHECKER_DIR"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

@check("python main.py --help works")
def _cli_help():
    r = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert r.returncode == 0, f"exit code {r.returncode}: {r.stderr}"
    assert "check" in r.stdout
    assert "batch" in r.stdout
    assert "labs" in r.stdout

@check("python -m autochecker --help works")
def _module_help():
    r = subprocess.run(
        [sys.executable, "-m", "autochecker", "--help"],
        capture_output=True, text=True, timeout=10, cwd=str(ROOT)
    )
    assert r.returncode == 0, f"exit code {r.returncode}: {r.stderr}"
    assert "check" in r.stdout

@check("python main.py labs works")
def _cli_labs():
    r = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "labs"],
        capture_output=True, text=True, timeout=10
    )
    assert r.returncode == 0, f"exit code {r.returncode}: {r.stderr}"
    assert "lab-01" in r.stdout
    assert "lab-02" in r.stdout


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

@check("lab-01 spec loads correctly")
def _spec_load():
    from autochecker.spec import load_spec
    spec = load_spec(str(ROOT / "specs" / "lab-01.yaml"))
    assert spec.id == "lab-01"
    assert len(spec.checks) > 0

@check("lab-02 spec loads correctly")
def _spec_load_02():
    from autochecker.spec import load_spec
    spec = load_spec(str(ROOT / "specs" / "lab-02.yaml"))
    assert spec.id == "lab-02"
    assert len(spec.checks) > 0


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

@check("Dockerfile syntax valid")
def _dockerfile():
    src = (ROOT / "deploy" / "Dockerfile").read_text()
    assert "COPY requirements.txt" in src
    assert "pip install" in src
    assert "CMD" in src

@check("docker-compose.yml references correct paths")
def _compose():
    src = (ROOT / "deploy" / "docker-compose.yml").read_text()
    assert "AUTOCHECKER_DIR" not in src
    assert "bot-data" in src
    assert "autochecker-results" in src


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\nRunning verification checks from {ROOT}\n")
    run_checks()
    print(f"\n{'=' * 40}")
    print(f"  {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 40}")
    sys.exit(1 if FAILED else 0)
