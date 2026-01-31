# autochecker/github_client.py
import requests
import json
import hashlib
import sys
import io
from pathlib import Path
from typing import List, Dict, Any, Optional

# Убеждаемся, что стандартный вывод использует UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE_DIR = Path(".autochecker_cache")
CACHE_DIR.mkdir(exist_ok=True)

class GitHubClient:
    """
    Клиент для взаимодействия с GitHub REST API.
    Реализует кэширование ответов API на диск.
    """
    def __init__(self, token: str, repo_owner: str, repo_name: str, use_cache: bool = True):
        self._owner = repo_owner
        self._repo_name = repo_name
        self._use_cache = use_cache
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self._base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        cache_status = "✅ ВКЛ" if use_cache else "❌ ВЫКЛ"
        print(f"🚀 Инициализирован GitHubClient для репозитория: {repo_owner}/{repo_name} (Кэш: {cache_status})")

    def _get_cached(self, endpoint: str) -> Optional[Any]:
        """Пытается получить ответ из кэша."""
        if not self._use_cache:
            return None
            
        cache_key = hashlib.md5(f"{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        if cache_file.exists():
            print(f"  CACHE HIT: {endpoint}")
            with open(cache_file, "r") as f:
                return json.load(f)
        print(f"  CACHE MISS: {endpoint}")
        return None

    def _set_cache(self, endpoint: str, data: Any):
        """Сохраняет ответ в кэш."""
        if not self._use_cache:
            return

        cache_key = hashlib.md5(f"{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def _get(self, endpoint: str, use_cache: Optional[bool] = None) -> Optional[Any]:
        """Выполняет GET-запрос с поддержкой кэширования."""
        # Если use_cache не передан явно, используем настройку экземпляра
        should_cache = self._use_cache if use_cache is None else use_cache
        
        full_endpoint_url = self._base_url
        if endpoint:
            full_endpoint_url += f"/{endpoint}"

        if should_cache:
            cached_data = self._get_cached(full_endpoint_url)
            if cached_data:
                return cached_data
        
        try:
            # Убеждаемся, что заголовки правильно закодированы
            safe_headers = {}
            for key, value in self._headers.items():
                if isinstance(value, str):
                    # Убеждаемся, что значение - это ASCII или правильно закодированная строка
                    try:
                        value.encode('ascii')
                        safe_headers[key] = value
                    except UnicodeEncodeError:
                        # Если есть не-ASCII символы, пробуем закодировать в UTF-8 и декодировать обратно
                        safe_headers[key] = value.encode('utf-8').decode('latin-1', errors='replace')
                else:
                    safe_headers[key] = value
            
            response = requests.get(full_endpoint_url, headers=safe_headers)
            response.raise_for_status()
            data = response.json()
            if should_cache:
                self._set_cache(full_endpoint_url, data)
            return data
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            if status_code == 404:
                try:
                    print(f"  ❌ Ресурс не найден: {full_endpoint_url}")
                except UnicodeEncodeError:
                    print(f"  [ERROR] Resource not found: {full_endpoint_url}")
                return None
            elif status_code == 401:
                try:
                    print(f"  ❌ Ошибка авторизации (401). Проверьте правильность GitHub токена.")
                except UnicodeEncodeError:
                    print(f"  [ERROR] Authorization failed (401). Check your GitHub token.")
                return None
            else:
                try:
                    print(f"  ❌ HTTP ошибка {status_code} при запросе к {full_endpoint_url}: {e}")
                except UnicodeEncodeError:
                    print(f"  [ERROR] HTTP error {status_code}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            try:
                print(f"  ❌ Ошибка сети при запросе к {full_endpoint_url}: {e}")
            except UnicodeEncodeError:
                print(f"  [ERROR] Network error: {e}")
            return None

    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Получает базовую информацию о репозитории."""
        # Для базовой информации кэш не используем, чтобы всегда иметь свежие данные
        return self._get("", use_cache=False)

    def get_commits(self, branch: str) -> List[Dict[str, Any]]:
        """Получает список коммитов для ветки."""
        return self._get(f"commits?sha={branch}&per_page=100") or []

    def get_issues(self) -> List[Dict[str, Any]]:
        """Получает список всех issues."""
        return self._get("issues?state=all&per_page=100") or []

    def get_pull_requests(self) -> List[Dict[str, Any]]:
        """Получает список всех pull requests."""
        return self._get("pulls?state=all&per_page=100") or []
    
    def get_pr_reviews(self, pr_number: int) -> List[Dict[str, Any]]:
        """Получает список reviews для PR."""
        return self._get(f"pulls/{pr_number}/reviews") or []
    
    def get_pr_review_comments(self, pr_number: int) -> List[Dict[str, Any]]:
        """Получает список line comments для PR."""
        return self._get(f"pulls/{pr_number}/comments") or []