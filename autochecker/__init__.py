# autochecker/__init__.py
"""Autochecker - Automated student work checker."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# Resolve paths relative to the repo root (parent of this package)
_PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = _PACKAGE_DIR.parent
SPECS_DIR = ROOT_DIR / "specs"
RESULTS_DIR = ROOT_DIR / "results"


@dataclass
class StudentCheckResult:
    """Result of checking a single student."""
    student_alias: str
    score: float
    passed: int
    failed: int
    total: int
    results: List[Dict]
    repo_url: Optional[str] = None
    results_json_path: Optional[Path] = None
    summary_html_path: Optional[Path] = None
    student_report_path: Optional[Path] = None
    error: Optional[str] = None


def check_student(
    student_alias: str,
    lab_id: str,
    task_filter: Optional[str] = None,
    platform: str = "github",
    gitlab_url: str = "https://gitlab.astanait.edu.kz",
    branch: Optional[str] = None,
    output_dir: Optional[str] = None,
    token: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    use_cache: bool = False,
    server_ip: Optional[str] = None,
    lms_api_key: Optional[str] = None,
    vm_username: Optional[str] = None,
) -> StudentCheckResult:
    """Check a single student's repository against a lab spec.

    This is the main programmatic API. The bot and CLI both call this.

    Returns a StudentCheckResult with score, file paths, and per-check details.
    Raises RuntimeError on fatal errors (repo not found, spec missing, etc.).
    """
    from .cli import LAB_CONFIG
    from .spec import load_spec
    from .batch_processor import create_client
    from .repo_reader import RepoReader
    from .engine import CheckEngine
    from .reporter import Reporter

    # Resolve lab config
    lab_config = LAB_CONFIG.get(lab_id)
    if not lab_config:
        raise RuntimeError(f"Unknown lab: {lab_id}")

    repo_name = lab_config["repo_suffix"]
    spec_path = SPECS_DIR / f"{lab_id}.yaml"

    if not spec_path.exists():
        raise RuntimeError(f"Spec file not found: {spec_path}")

    # Resolve output directory
    if output_dir is None:
        output_dir = str(RESULTS_DIR)

    # Resolve tokens from env if not provided
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITLAB_TOKEN")
    if not token:
        raise RuntimeError("No API token found. Set GITHUB_TOKEN or GITLAB_TOKEN.")

    if not openrouter_api_key:
        openrouter_api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")

    lab_spec = load_spec(str(spec_path))
    lab_spec.repo_name = repo_name

    # Prepare output directory
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    student_results_dir = out / student_alias
    student_results_dir.mkdir(exist_ok=True)

    for old_file in ["summary.html", "results.jsonl"]:
        old_path = student_results_dir / old_file
        if old_path.exists():
            old_path.unlink()

    # Create API client
    client = create_client(
        platform=platform,
        token=token,
        repo_owner=student_alias,
        repo_name=repo_name,
        gitlab_url=gitlab_url,
        use_cache=use_cache,
    )

    # Check repo accessibility
    repo_info = client.get_repo_info()
    if not repo_info:
        reporter = Reporter(student_alias=student_alias, results=[])
        reporter.write_failure_report(student_results_dir, "Repository not found")
        raise RuntimeError("Repository not found or inaccessible")

    if repo_info.get("private"):
        reporter = Reporter(student_alias=student_alias, results=[])
        reporter.write_failure_report(student_results_dir, "Repository is private")
        raise RuntimeError("Repository is private")

    # Download archive
    reader = RepoReader(
        owner=student_alias,
        repo_name=repo_name,
        token=token,
        platform=platform,
        gitlab_url=gitlab_url,
        branch=branch,
    )

    # Determine branch
    check_branch = branch
    if not check_branch and hasattr(lab_spec, "discovery") and lab_spec.discovery:
        check_branch = lab_spec.discovery.get("default_branch")

    # Filter checks by task
    checks_to_run = lab_spec.checks
    if task_filter:
        checks_to_run = [c for c in checks_to_run if c.task == task_filter or c.task is None]
        if not checks_to_run:
            raise RuntimeError(f"No checks found for task '{task_filter}'")

    # Resolve task title
    task_title = None
    if task_filter and lab_spec.tasks:
        for t in lab_spec.tasks:
            if t.id == task_filter:
                task_title = t.title
                break

    # Split checks by runner type
    code_checks = [c for c in checks_to_run if c.runner != "llm"]
    llm_checks = [c for c in checks_to_run if c.runner == "llm"]

    # Run code checks
    engine = CheckEngine(client, reader, branch=check_branch, lab_spec=lab_spec,
                         server_ip=server_ip, lms_api_key=lms_api_key,
                         vm_username=vm_username)
    results = []
    for check_spec in code_checks:
        check_description = check_spec.title or check_spec.description or check_spec.id
        check_hint = check_spec.hint or ""
        result = engine.run_check(
            check_spec.id, check_spec.type, check_spec.params, check_description, hint=check_hint
        )
        results.append(result)

    # LLM atomic checks
    if openrouter_api_key and llm_checks:
        try:
            from .llm_analyzer import run_llm_check

            for check_spec in llm_checks:
                check_description = check_spec.title or check_spec.description or check_spec.id
                llm_result = run_llm_check(
                    openrouter_api_key=openrouter_api_key,
                    reader=reader,
                    check_id=check_spec.id,
                    check_params=check_spec.params,
                    check_title=check_description,
                    client=client,
                )
                results.append(
                    {
                        "id": llm_result.get("id"),
                        "status": llm_result.get("status", "ERROR"),
                        "details": llm_result.get("details", ""),
                        "description": llm_result.get("description", check_description),
                        "score": llm_result.get("score"),
                        "min_score": llm_result.get("min_score"),
                        "reasons": llm_result.get("reasons", []),
                        "quotes": llm_result.get("quotes", []),
                    }
                )
        except Exception as e:
            for check_spec in llm_checks:
                results.append(
                    {
                        "id": check_spec.id,
                        "status": "ERROR",
                        "details": f"LLM analysis error: {str(e)[:100]}",
                        "description": check_spec.title or check_spec.description or check_spec.id,
                    }
                )

    # Deep repo analysis (only when spec has LLM checks)
    llm_analysis = None
    if openrouter_api_key and llm_checks:
        try:
            from .llm_analyzer import analyze_repo

            llm_analysis = analyze_repo(
                openrouter_api_key=openrouter_api_key,
                reader=reader,
                client=client,
                lab_spec=lab_spec,
                repo_owner=student_alias,
                check_results=results,
            )
        except Exception as e:
            llm_analysis = {
                "verdict": "analysis_failed",
                "reasons": [f"Error: {str(e)[:100]}"],
            }

    # Save reports
    reporter = Reporter(
        student_alias=student_alias,
        results=results,
        repo_url=repo_info.get("html_url"),
        llm_analysis=llm_analysis,
        task_title=task_title,
    )
    reporter.write_jsonl(student_results_dir)
    reporter.write_html(student_results_dir)
    reporter.write_student_report(student_results_dir)

    # Calculate score
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    score = (passed / total * 100) if total > 0 else 0

    return StudentCheckResult(
        student_alias=student_alias,
        score=score,
        passed=passed,
        failed=total - passed,
        total=total,
        results=results,
        repo_url=repo_info.get("html_url"),
        results_json_path=student_results_dir / "results.jsonl",
        summary_html_path=student_results_dir / "summary.html",
        student_report_path=student_results_dir / "student_report.txt",
    )
