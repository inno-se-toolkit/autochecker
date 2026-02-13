# autochecker/cli.py
"""CLI interface for Autochecker using Typer."""

import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from . import ROOT_DIR, SPECS_DIR, RESULTS_DIR, check_student

# Create Typer application
app = typer.Typer(help="Autochecker - Automated student work checker")

load_dotenv()

# Lab configuration
LAB_CONFIG = {
    "lab-01": {
        "name": "Lab 01 – Products, Architecture & Roles",
        "repo_suffix": "lab-01-market-product-and-git",
        "spec": "specs/lab-01.yaml",
        "ready": True,
    },
    "lab-02": {
        "name": "Lab 02 — Run, Fix, and Deploy a Backend Service",
        "repo_suffix": "se-toolkit-lab-2",
        "spec": "specs/lab-02.yaml",
        "ready": True,
    },
    "lab-03": {
        "name": "Lab 03 – (Coming soon)",
        "repo_suffix": "lab-03-tbd",
        "spec": "specs/lab-03.yaml",
        "ready": False,
    },
    "lab-04": {
        "name": "Lab 04 – (Coming soon)",
        "repo_suffix": "lab-04-tbd",
        "spec": "specs/lab-04.yaml",
        "ready": False,
    },
    "lab-05": {
        "name": "Lab 05 – (Coming soon)",
        "repo_suffix": "lab-05-tbd",
        "spec": "specs/lab-05.yaml",
        "ready": False,
    },
    "lab-06": {
        "name": "Lab 06 – (Coming soon)",
        "repo_suffix": "lab-06-tbd",
        "spec": "specs/lab-06.yaml",
        "ready": False,
    },
    "lab-07": {
        "name": "Lab 07 – (Coming soon)",
        "repo_suffix": "lab-07-tbd",
        "spec": "specs/lab-07.yaml",
        "ready": False,
    },
    "lab-08": {
        "name": "Lab 08 – (Coming soon)",
        "repo_suffix": "lab-08-tbd",
        "spec": "specs/lab-08.yaml",
        "ready": False,
    },
    "lab-09": {
        "name": "Lab 09 – (Coming soon)",
        "repo_suffix": "lab-09-tbd",
        "spec": "specs/lab-09.yaml",
        "ready": False,
    },
    "lab-10": {
        "name": "Lab 10 – (Coming soon)",
        "repo_suffix": "lab-10-tbd",
        "spec": "specs/lab-10.yaml",
        "ready": False,
    },
}


def select_platform() -> tuple:
    """Interactive platform selection."""
    print("\n" + "=" * 50)
    print("SELECT PLATFORM")
    print("=" * 50)
    print("  1. GitHub (github.com)")
    print("  2. GitLab (gitlab.astanait.edu.kz)")
    print("  3. GitLab (other server)")
    print("-" * 50)

    choice = input("Select platform [1]: ").strip() or "1"

    if choice == "2":
        return "gitlab", "https://gitlab.astanait.edu.kz"
    elif choice == "3":
        url = input("Enter GitLab server URL: ").strip()
        return "gitlab", url
    else:
        return "github", "https://github.com"


def select_lab() -> dict:
    """Interactive lab selection."""
    print("\n" + "=" * 50)
    print("SELECT LAB")
    print("=" * 50)

    for i, (lab_id, config) in enumerate(LAB_CONFIG.items(), 1):
        status = "Ready" if config["ready"] else "Coming soon"
        print(f"  {i}. [{status}] {config['name']}")

    print("-" * 50)
    choice = input("Select lab [1]: ").strip() or "1"

    try:
        idx = int(choice) - 1
        lab_id = list(LAB_CONFIG.keys())[idx]
        config = LAB_CONFIG[lab_id]

        if not config["ready"]:
            print(f"  {config['name']} is not ready yet!")
            print("   Only Lab 01 is available for now.")
            return "lab-01", LAB_CONFIG["lab-01"]

        return lab_id, config
    except (ValueError, IndexError):
        print("  Invalid choice, using Lab 01")
        return "lab-01", LAB_CONFIG["lab-01"]


@app.command()
def check(
    student: str = typer.Option(None, "--student", "-s", help="GitHub/GitLab student username"),
    lab: str = typer.Option(None, "--lab", "-l", help="Lab number (lab-01, lab-02, ...)"),
    task: str = typer.Option(None, "--task", "-t", help="Task ID to check (task-0, task-1, workflow, ...)"),
    platform: str = typer.Option(None, "--platform", "-p", help="Platform: github or gitlab"),
    gitlab_url: str = typer.Option("https://gitlab.astanait.edu.kz", "--gitlab-url", help="GitLab server URL"),
    output_dir: str = typer.Option(None, "--output", "-o", help="Output directory for results"),
    token: str = typer.Option(None, envvar=["GITHUB_TOKEN", "GITLAB_TOKEN"], help="Access Token"),
    openrouter_api_key: str = typer.Option(None, envvar="OPENROUTER_API_KEY", help="OpenRouter API Key"),
    branch: str = typer.Option(None, "--branch", "-b", help="Branch to check (defaults to spec or main)"),
    cache: bool = typer.Option(False, "--cache", help="Enable API response caching (off by default for single checks)"),
):
    """
    Check a single student.

    Examples:
      python main.py check -s Nurassyl28 -l lab-01 -p github
      python main.py check -s Nurassyl28 -l lab-01 -t task-1 -p github
      python main.py check  # interactive mode
    """
    # Check token
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITLAB_TOKEN")

    if not token:
        print("Token not found! Add GITHUB_TOKEN or GITLAB_TOKEN to .env")
        raise typer.Exit(code=1)

    # Interactive mode if parameters not specified
    if not platform:
        platform, gitlab_url = select_platform()

    if not lab:
        lab, lab_config = select_lab()
    else:
        lab_config = LAB_CONFIG.get(lab, LAB_CONFIG["lab-01"])

    # Check if a file was passed instead of a student name
    if student and (student.endswith(".csv") or student.endswith(".txt") or student.endswith(".json")):
        print(f"\nERROR: You specified a file '{student}' instead of a student name!")
        print(f"\nTo check a single student use:")
        print(f"   python3 main.py check -s StudentName -l lab-01 -p github")
        print(f"\nTo check all students from a file use the 'batch' command:")
        print(f"   python3 main.py batch -s {student} -l lab-01 -p github")
        raise typer.Exit(code=1)

    if not student:
        platform_name = "GitLab" if platform == "gitlab" else "GitHub"
        print("\n" + "=" * 50)
        print(f"STUDENT ({platform_name})")
        print("=" * 50)
        student = input("Enter student username: ").strip()

    if not student:
        print("No student specified!")
        raise typer.Exit(code=1)

    # Resolve output dir
    if output_dir is None:
        output_dir = str(RESULTS_DIR)

    repo_name = lab_config["repo_suffix"]

    print("\n" + "=" * 50)
    print("STARTING CHECK")
    print("=" * 50)
    print(f"  Platform: {platform}")
    print(f"  Student:  {student}")
    print(f"  Repo:     {repo_name}")
    print(f"  Lab:      {lab_config['name']}")
    print("=" * 50 + "\n")

    # Get OpenRouter API key
    openrouter_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")

    if not openrouter_key:
        print("  OpenRouter API key not found. LLM checks will be skipped.")
        print("   Add OPENROUTER_API_KEY to .env or use --openrouter-api-key")

    try:
        result = check_student(
            student_alias=student,
            lab_id=lab,
            task_filter=task,
            platform=platform,
            gitlab_url=gitlab_url,
            branch=branch,
            output_dir=output_dir,
            token=token,
            openrouter_api_key=openrouter_key,
            use_cache=cache,
        )

        print(f"\n{'=' * 50}")
        print(f"RESULT: {result.score:.1f}% ({result.passed}/{result.total})")
        print(f"Report: {result.summary_html_path}")
        print(f"{'=' * 50}\n")

    except RuntimeError as e:
        print(f"\n  Error: {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        print(f"\n  Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def batch(
    students_file: Path = typer.Option(..., "--students", "-s", help="File with student list (CSV/JSON/TXT)"),
    lab: str = typer.Option("lab-01", "--lab", "-l", help="Lab number: lab-01, lab-02, ..."),
    platform: str = typer.Option("github", "--platform", "-p", help="Platform: github or gitlab"),
    gitlab_url: str = typer.Option("https://gitlab.astanait.edu.kz", "--gitlab-url", help="GitLab server URL"),
    output_dir: str = typer.Option(None, "--output", "-o", help="Output directory for results"),
    token: str = typer.Option(None, envvar=["GITHUB_TOKEN", "GITLAB_TOKEN"], help="Access Token"),
    openrouter_api_key: str = typer.Option(None, envvar="OPENROUTER_API_KEY", help="OpenRouter API Key"),
    branch: str = typer.Option(None, "--branch", "-b", help="Branch to check (defaults to spec or main)"),
    max_workers: int = typer.Option(2, "--workers", "-w", help="Parallel workers (2-3 recommended)"),
    check_plagiarism: bool = typer.Option(True, "--plagiarism/--no-plagiarism", help="Plagiarism check"),
    plagiarism_threshold: float = typer.Option(0.5, "--threshold", help="Plagiarism threshold (0.0-1.0)"),
    cache: bool = typer.Option(False, "--cache", help="Enable persistent API response caching"),
):
    """
    Batch student check (up to 300+ students).

    Examples:
      python main.py batch -s students.csv -l lab-01 -p github
      python main.py batch -s students.csv -l lab-01 -p gitlab --gitlab-url https://gitlab.astanait.edu.kz
    """
    # Check token
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITLAB_TOKEN")

    if not token:
        print("Token not found! Add GITHUB_TOKEN or GITLAB_TOKEN to .env")
        raise typer.Exit(code=1)

    # Get lab config
    lab_config = LAB_CONFIG.get(lab)
    if not lab_config:
        print(f"Lab '{lab}' not found!")
        print(f"   Available: {', '.join(LAB_CONFIG.keys())}")
        raise typer.Exit(code=1)

    if not lab_config["ready"]:
        print(f"  {lab_config['name']} is not ready yet!")
        raise typer.Exit(code=1)

    repo_name = lab_config["repo_suffix"]
    spec_path = str(SPECS_DIR / f"{lab}.yaml")

    # Resolve output dir
    if output_dir is None:
        output_dir = str(RESULTS_DIR)

    # Get OpenRouter API key
    openrouter_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
    if not openrouter_key:
        print("  OpenRouter API key not found. LLM checks will be skipped.")
        print("   Add OPENROUTER_API_KEY to .env or use --openrouter-api-key")

    print("\n" + "=" * 60)
    print("BATCH CHECK")
    print("=" * 60)
    print(f"  Platform:  {platform}")
    print(f"  Lab:       {lab_config['name']}")
    print(f"  Repo:      {repo_name}")
    print(f"  Students:  {students_file}")
    print(f"  LLM:       {'Enabled' if openrouter_key else 'Not configured'}")
    print(f"  Plagiarism: {'Enabled' if check_plagiarism else 'Disabled'}")
    print(f"  Workers:   {max_workers}")
    print("=" * 60 + "\n")

    try:
        from .batch_processor import process_batch

        process_batch(
            students_file=str(students_file),
            repo_name=repo_name,
            spec_path=spec_path,
            token=token,
            openrouter_api_key=openrouter_key,
            output_dir=output_dir,
            max_workers=max_workers,
            check_plagiarism=check_plagiarism,
            plagiarism_threshold=plagiarism_threshold,
            platform=platform,
            gitlab_url=gitlab_url,
            branch=branch,
            no_cache=not cache,
        )
    except Exception as e:
        print(f"\n  Error: {e}")
        raise typer.Exit(code=1)


@app.command()
def labs():
    """Show list of available labs."""
    print("\n" + "=" * 60)
    print("LABS")
    print("=" * 60)

    for lab_id, config in LAB_CONFIG.items():
        status = "Ready" if config["ready"] else "In development"
        print(f"\n  {lab_id}:")
        print(f"    Name:   {config['name']}")
        print(f"    Repo:   {config['repo_suffix']}")
        print(f"    Status: {status}")

    print("\n" + "=" * 60)
    print("Usage:")
    print("   python main.py check -s StudentName -l lab-01")
    print("   python main.py batch -s students.csv -l lab-01")
    print("=" * 60 + "\n")
