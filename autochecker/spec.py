# autochecker/spec.py
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
import yaml

class CheckSpec(BaseModel):
    """Спецификация одной проверки в YAML."""
    id: str
    type: str
    runner: str = Field(default="code")  # "code" для автоматических проверок, "llm" для LLM-анализа
    check_class: Optional[str] = Field(default=None, alias="class")  # structural, process, content
    params: Dict[str, Any] = Field(default_factory=dict)  # Параметры проверки (опциональные)
    description: str = Field(default="")  # Описание проверки (опциональное)
    title: str = Field(default="")  # Заголовок проверки (опциональный, для совместимости)
    required: bool = Field(default=True)  # Обязательность проверки (опциональный)
    is_required: bool = Field(default=True)  # Обязательность проверки (новый формат)
    weight: float = Field(default=1.0)  # Вес проверки для взвешенной оценки (опциональный)
    depends_on: List[str] = Field(default_factory=list)  # Зависимости от других проверок
    
    class Config:
        populate_by_name = True  # Позволяет использовать alias "class" для check_class


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
    # Дополнительные поля из новых спецификаций (опциональные)
    discovery: Optional[Dict[str, Any]] = Field(default=None)
    runtime: Optional[Dict[str, Any]] = Field(default=None)
    scoring: Optional[Dict[str, Any]] = Field(default=None)
    
    class Config:
        extra = "ignore"  # Игнорируем неизвестные поля

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
