"""Configuration module for the bot."""

import csv
import os
import yaml
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")

# Database configuration
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Project paths — resolved from monorepo root
BASE_DIR = Path(__file__).resolve().parent.parent
SPECS_DIR = BASE_DIR / "specs"
RESULTS_DIR = BASE_DIR / "results"
EXECUTION_TIMEOUT = 120  # seconds
MAX_ATTEMPTS_PER_TASK = int(os.getenv("MAX_ATTEMPTS_PER_TASK", "3"))

# Active labs — controls which tasks appear in the bot
# Comma-separated list in env var, e.g. "lab-01,lab-02"
ACTIVE_LABS = [l.strip() for l in os.getenv("ACTIVE_LABS", "lab-01").split(",") if l.strip()]

# Email whitelist — only these emails can register
# Dict maps email -> student group (empty string if no group)
_whitelist_csv = Path(__file__).resolve().parent / "allowed_emails.csv"
_whitelist_txt = Path(__file__).resolve().parent / "allowed_emails.txt"
ALLOWED_EMAILS: dict[str, str] = {}
if _whitelist_csv.exists():
    with open(_whitelist_csv, encoding="utf-8") as _f:
        for _row in csv.DictReader(_f):
            _email = _row["email"].strip().lower()
            if _email:
                ALLOWED_EMAILS[_email] = _row.get("group", "").strip()
elif _whitelist_txt.exists():
    ALLOWED_EMAILS = {
        line.strip().lower(): ""
        for line in _whitelist_txt.read_text().splitlines()
        if line.strip()
    }


@dataclass
class TaskInfo:
    """Info about a checkable task."""
    lab_id: str
    task_id: str
    title: str
    prerequisite: Optional[str] = None  # task_id that must be passed first


def load_tasks_from_spec(lab_id: str) -> List[TaskInfo]:
    """Load task metadata from a lab spec YAML file."""
    spec_path = SPECS_DIR / f"{lab_id}.yaml"
    if not spec_path.exists():
        return []

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    tasks = []
    for task in spec.get("tasks", []):
        tasks.append(TaskInfo(
            lab_id=lab_id,
            task_id=task["id"],
            title=task["title"],
            prerequisite=task.get("prerequisite"),
        ))
    return tasks


def get_active_tasks() -> List[TaskInfo]:
    """Get all tasks from active labs."""
    all_tasks = []
    for lab_id in ACTIVE_LABS:
        all_tasks.extend(load_tasks_from_spec(lab_id))
    return all_tasks


def get_lab_titles() -> dict[str, str]:
    """Return {lab_id: title} for every active lab."""
    titles = {}
    for lab_id in ACTIVE_LABS:
        spec_path = SPECS_DIR / f"{lab_id}.yaml"
        if spec_path.exists():
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = yaml.safe_load(f)
            titles[lab_id] = spec.get("title", lab_id)
        else:
            titles[lab_id] = lab_id
    return titles
