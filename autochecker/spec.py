# autochecker/spec.py
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
import yaml

class CheckSpec(BaseModel):
    """Specification for a single check in YAML."""
    id: str
    type: str
    runner: str = Field(default="code")  # "code" for automated checks, "llm" for LLM analysis
    check_class: Optional[str] = Field(default=None, alias="class")  # structural, process, content
    task: Optional[str] = Field(default=None)  # Task group ID (e.g. "task-0", "task-1", "workflow")
    hint: Optional[str] = Field(default=None)  # Student-facing hint shown on failure
    params: Dict[str, Any] = Field(default_factory=dict)  # Check parameters (optional)
    description: str = Field(default="")  # Check description (optional)
    title: str = Field(default="")  # Check title (optional, for compatibility)
    required: bool = Field(default=True)  # Check is required
    is_required: bool = Field(default=True)  # Check is required (new format)
    weight: float = Field(default=1.0)  # Check weight for weighted scoring (optional)
    depends_on: List[str] = Field(default_factory=list)  # Dependencies on other checks

    class Config:
        populate_by_name = True  # Allows using alias "class" for check_class


class TaskMeta(BaseModel):
    """Metadata for a task group within a lab spec."""
    id: str
    title: str


class PlagiarismConfig(BaseModel):
    """Plagiarism check configuration."""
    enabled: bool = Field(default=True)  # Whether check is enabled
    threshold: float = Field(default=0.8)  # Similarity threshold (0.0-1.0)
    # Files/dirs to check (if empty - all code files are checked)
    include_paths: List[str] = Field(default_factory=list)
    # Files/dirs to exclude (in addition to standard ones)
    exclude_paths: List[str] = Field(default_factory=list)
    # File extensions to check (if empty - standard ones are used)
    include_extensions: List[str] = Field(default_factory=list)


class LabSpec(BaseModel):
    """Lab specification (YAML file)."""
    id: str
    repo_name: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default="")  # Lab title (optional)
    tasks: List[TaskMeta] = Field(default_factory=list)  # Task group metadata
    checks: List[CheckSpec]
    # Plagiarism config for this lab
    plagiarism: Optional[PlagiarismConfig] = Field(default=None)
    # Additional fields from new specs (optional)
    discovery: Optional[Dict[str, Any]] = Field(default=None)
    runtime: Optional[Dict[str, Any]] = Field(default=None)
    scoring: Optional[Dict[str, Any]] = Field(default=None)

    class Config:
        extra = "ignore"  # Ignore unknown fields

def load_spec(path: str) -> LabSpec:
    """Loads and validates specification from YAML file."""
    print(f"Loading spec from {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Use model_validate for Pydantic v2, fallback to parse_obj for v1
    try:
        spec = LabSpec.model_validate(data)
    except AttributeError:
        # For Pydantic v1 compatibility
        spec = LabSpec.parse_obj(data)
    print(f"Spec '{spec.id}' loaded successfully. Number of checks: {len(spec.checks)}")
    return spec
