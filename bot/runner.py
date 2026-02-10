"""Execution engine for running Autochecker via direct import."""

import asyncio
import functools
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from .config import RESULTS_DIR, EXECUTION_TIMEOUT


@dataclass
class CheckResult:
    """Result of an Autochecker run."""
    success: bool
    results_json_path: Optional[Path] = None
    summary_html_path: Optional[Path] = None
    student_report_path: Optional[Path] = None
    score: Optional[str] = None
    error_message: Optional[str] = None


def _run_check_sync(student_name: str, lab_id: str, task_id: Optional[str] = None) -> CheckResult:
    """Synchronous wrapper that calls check_student directly."""
    from autochecker import check_student

    try:
        result = check_student(
            student_alias=student_name,
            lab_id=lab_id,
            task_filter=task_id,
            platform="github",
            output_dir=str(RESULTS_DIR),
        )

        return CheckResult(
            success=True,
            results_json_path=result.results_json_path,
            summary_html_path=result.summary_html_path,
            student_report_path=result.student_report_path,
            score=f"{result.score:.1f}% ({result.passed}/{result.total})",
        )

    except RuntimeError as e:
        # Expected errors (repo not found, private, etc.)
        # Check if failure report was written
        results_dir = RESULTS_DIR / student_name
        summary_html = results_dir / "summary.html"

        return CheckResult(
            success=False,
            summary_html_path=summary_html if summary_html.exists() else None,
            error_message=str(e),
        )
    except Exception as e:
        return CheckResult(
            success=False,
            error_message=f"Unexpected error: {str(e)[:300]}",
        )


async def run_check(student_name: str, lab_id: str, task_id: Optional[str] = None) -> CheckResult:
    """
    Run the Autochecker asynchronously via run_in_executor.

    Args:
        student_name: The student's GitHub username
        lab_id: The lab identifier (e.g. "lab-01")
        task_id: Optional task identifier (e.g. "task-1")

    Returns:
        CheckResult with execution details and file paths
    """
    loop = asyncio.get_running_loop()

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                functools.partial(_run_check_sync, student_name, lab_id, task_id),
            ),
            timeout=EXECUTION_TIMEOUT,
        )

        # Parse score from JSONL if not set by direct call
        if result.results_json_path and result.results_json_path.exists() and not result.score:
            try:
                with open(result.results_json_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if "score" in data:
                            result.score = str(data["score"])
            except (json.JSONDecodeError, IOError):
                pass

        return result

    except asyncio.TimeoutError:
        return CheckResult(
            success=False,
            error_message=f"Timeout: Check exceeded {EXECUTION_TIMEOUT} seconds and was terminated.",
        )
    except Exception as e:
        return CheckResult(
            success=False,
            error_message=f"Unexpected error: {str(e)[:300]}",
        )
