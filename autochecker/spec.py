# autochecker/spec.py
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import yaml

class CheckSpec(BaseModel):
    """Спецификация одной проверки в YAML."""
    id: str
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)  # Параметры проверки (опциональные)
    description: str = Field(default="")  # Описание проверки (опциональное)
    title: str = Field(default="")  # Заголовок проверки (опциональный, для совместимости)
    required: bool = Field(default=True)  # Обязательность проверки (опциональный)
    weight: float = Field(default=1.0)  # Вес проверки для взвешенной оценки (опциональный)


class PlagiarismConfig(BaseModel):
    """Конфигурация проверки плагиата."""
    enabled: bool = Field(default=True)  # Включена ли проверка
    threshold: float = Field(default=0.8)  # Порог схожести (0.0-1.0)
    # Файлы/папки для проверки (если пусто - проверяются все код-файлы)
    include_paths: List[str] = Field(default_factory=list)
    # Файлы/папки для исключения (дополнительно к стандартным)
    exclude_paths: List[str] = Field(default_factory=list)
    # Расширения файлов для проверки (если пусто - используются стандартные)
    include_extensions: List[str] = Field(default_factory=list)


class LabSpec(BaseModel):
    """Спецификация лабораторной работы (YAML файл)."""
    id: str
    repo_name: str
    title: Optional[str] = Field(default="")  # Название лабы (опционально)
    checks: List[CheckSpec]
    # Конфигурация плагиата для этой лабы
    plagiarism: Optional[PlagiarismConfig] = Field(default=None)

def load_spec(path: str) -> LabSpec:
    """Загружает и валидирует спецификацию из YAML файла."""
    print(f"⚙️ Загрузка спецификации из {path}...")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Используем model_validate для Pydantic v2, fallback на parse_obj для v1
    try:
        spec = LabSpec.model_validate(data)
    except AttributeError:
        # Для совместимости с Pydantic v1
        spec = LabSpec.parse_obj(data)
    print(f"✅ Спецификация '{spec.id}' успешно загружена. Количество проверок: {len(spec.checks)}")
    return spec
