# autochecker/gitlab_client.py
"""
Клиент для взаимодействия с GitLab REST API.
Аналогичен github_client.py, но для GitLab.
"""
import requests
import json
import hashlib
import sys
import io
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

# Убеждаемся, что стандартный вывод использует UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE_DIR = Path(".autochecker_cache")
CACHE_DIR.mkdir(exist_ok=True)


class GitLabClient:
    """
    Клиент для взаимодействия с GitLab REST API.
    Реализует кэширование ответов API на диск.
    
    Поддерживает как gitlab.com, так и self-hosted GitLab.
    """
    
    def __init__(self, token: str, repo_owner: str, repo_name: str, gitlab_url: str = "https://gitlab.com"):
        """
        Args:
            token: GitLab Personal Access Token (PAT) или Project Access Token
            repo_owner: Владелец проекта (username или group)
            repo_name: Имя проекта
            gitlab_url: URL GitLab сервера (по умолчанию gitlab.com)
        """
        self._owner = repo_owner
        self._repo_name = repo_name
        self._gitlab_url = gitlab_url.rstrip('/')
        
        # GitLab использует project_id в формате "owner%2Frepo_name" (URL-encoded)
        self._project_path = f"{repo_owner}/{repo_name}"
        self._project_id = urllib.parse.quote(self._project_path, safe='')
        
        self._headers = {
            "PRIVATE-TOKEN": token,
            "Accept": "application/json"
        }
        self._base_url = f"{self._gitlab_url}/api/v4/projects/{self._project_id}"
        print(f"🚀 Инициализирован GitLabClient для проекта: {self._project_path}")

    def _get_cached(self, endpoint: str) -> Optional[Any]:
        """Пытается получить ответ из кэша."""
        cache_key = hashlib.md5(f"gitlab_{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        if cache_file.exists():
            print(f"  CACHE HIT: {endpoint}")
            with open(cache_file, "r") as f:
                return json.load(f)
        print(f"  CACHE MISS: {endpoint}")
        return None

    def _set_cache(self, endpoint: str, data: Any):
        """Сохраняет ответ в кэш."""
        cache_key = hashlib.md5(f"gitlab_{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def _get(self, endpoint: str, use_cache: bool = True, params: Dict = None) -> Optional[Any]:
        """Выполняет GET-запрос с поддержкой кэширования."""
        full_endpoint_url = self._base_url
        if endpoint:
            full_endpoint_url += f"/{endpoint}"

        # Добавляем параметры в URL для кэширования
        cache_key_url = full_endpoint_url
        if params:
            cache_key_url += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

        if use_cache:
            cached_data = self._get_cached(cache_key_url)
            if cached_data:
                return cached_data
        
        try:
            response = requests.get(full_endpoint_url, headers=self._headers, params=params)
            response.raise_for_status()
            data = response.json()
            if use_cache:
                self._set_cache(cache_key_url, data)
            return data
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            if status_code == 404:
                print(f"  ❌ Проект не найден: {self._project_path}")
                return None
            elif status_code == 401:
                print(f"  ❌ Ошибка авторизации (401). Проверьте правильность GitLab токена.")
                return None
            elif status_code == 403:
                print(f"  ❌ Доступ запрещен (403). Проверьте права токена.")
                return None
            else:
                print(f"  ❌ HTTP ошибка {status_code} при запросе к {full_endpoint_url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Ошибка сети при запросе к {full_endpoint_url}: {e}")
            return None

    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Получает базовую информацию о проекте."""
        data = self._get("", use_cache=False)
        if data:
            # Преобразуем GitLab формат в GitHub-совместимый
            return {
                'id': data.get('id'),
                'name': data.get('name'),
                'full_name': data.get('path_with_namespace'),
                'html_url': data.get('web_url'),
                'description': data.get('description'),
                'private': data.get('visibility') == 'private',
                'default_branch': data.get('default_branch', 'main'),
                'owner': {
                    'login': self._owner
                },
                # GitLab-specific
                'visibility': data.get('visibility'),
                'archived': data.get('archived', False)
            }
        return None

    def get_commits(self, branch: str = None) -> List[Dict[str, Any]]:
        """
        Получает список коммитов для ветки.
        Возвращает в GitHub-совместимом формате.
        """
        params = {'per_page': 100}
        if branch:
            params['ref_name'] = branch
        
        data = self._get("repository/commits", params=params) or []
        
        # Преобразуем в GitHub-совместимый формат
        commits = []
        for item in data:
            commits.append({
                'sha': item.get('id'),
                'commit': {
                    'message': item.get('message', ''),
                    'author': {
                        'name': item.get('author_name', ''),
                        'email': item.get('author_email', ''),
                        'date': item.get('authored_date', '')
                    },
                    'committer': {
                        'name': item.get('committer_name', ''),
                        'email': item.get('committer_email', ''),
                        'date': item.get('committed_date', '')
                    }
                },
                'author': {
                    'login': item.get('author_name', '')
                },
                'html_url': item.get('web_url', '')
            })
        return commits

    def get_issues(self) -> List[Dict[str, Any]]:
        """
        Получает список всех issues.
        Возвращает в GitHub-совместимом формате.
        """
        params = {'per_page': 100, 'state': 'all'}
        data = self._get("issues", params=params) or []
        
        # Преобразуем в GitHub-совместимый формат
        issues = []
        for item in data:
            issues.append({
                'number': item.get('iid'),  # GitLab использует iid для project-level ID
                'id': item.get('id'),
                'title': item.get('title', ''),
                'body': item.get('description', ''),
                'state': 'open' if item.get('state') == 'opened' else item.get('state'),
                'html_url': item.get('web_url', ''),
                'user': {
                    'login': item.get('author', {}).get('username', '')
                },
                'labels': [label.get('name', '') if isinstance(label, dict) else label 
                          for label in item.get('labels', [])],
                'created_at': item.get('created_at'),
                'updated_at': item.get('updated_at'),
                'closed_at': item.get('closed_at')
            })
        return issues

    def get_pull_requests(self) -> List[Dict[str, Any]]:
        """
        Получает список всех merge requests (аналог pull requests в GitHub).
        Возвращает в GitHub-совместимом формате.
        """
        params = {'per_page': 100, 'state': 'all'}
        data = self._get("merge_requests", params=params) or []
        
        # Преобразуем в GitHub-совместимый формат
        prs = []
        for item in data:
            prs.append({
                'number': item.get('iid'),
                'id': item.get('id'),
                'title': item.get('title', ''),
                'body': item.get('description', ''),
                'state': 'open' if item.get('state') == 'opened' else item.get('state'),
                'merged': item.get('state') == 'merged',
                'html_url': item.get('web_url', ''),
                'user': {
                    'login': item.get('author', {}).get('username', '')
                },
                'head': {
                    'ref': item.get('source_branch', ''),
                    'sha': item.get('sha', '')
                },
                'base': {
                    'ref': item.get('target_branch', '')
                },
                'created_at': item.get('created_at'),
                'updated_at': item.get('updated_at'),
                'merged_at': item.get('merged_at')
            })
        return prs

    def get_branches(self) -> List[Dict[str, Any]]:
        """Получает список веток."""
        data = self._get("repository/branches", params={'per_page': 100}) or []
        
        branches = []
        for item in data:
            branches.append({
                'name': item.get('name'),
                'commit': {
                    'sha': item.get('commit', {}).get('id', '')
                },
                'protected': item.get('protected', False)
            })
        return branches

    def get_branch_protection(self, branch: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о защите ветки."""
        branch_encoded = urllib.parse.quote(branch, safe='')
        data = self._get(f"protected_branches/{branch_encoded}")
        if data:
            return {
                'name': data.get('name'),
                'protected': True,
                'required_pull_request_reviews': {
                    'required_approving_review_count': data.get('merge_access_levels', [{}])[0].get('access_level', 0)
                },
                'enforce_admins': data.get('code_owner_approval_required', False)
            }
        return None

    def get_file_content(self, path: str, ref: str = None) -> Optional[str]:
        """Получает содержимое файла из репозитория."""
        path_encoded = urllib.parse.quote(path, safe='')
        params = {}
        if ref:
            params['ref'] = ref
        
        data = self._get(f"repository/files/{path_encoded}", params=params)
        if data and 'content' in data:
            import base64
            try:
                return base64.b64decode(data['content']).decode('utf-8')
            except:
                return None
        return None

    def download_repository(self, ref: str = None) -> Optional[bytes]:
        """
        Скачивает репозиторий как zip-архив.
        
        Args:
            ref: Ветка или коммит для скачивания (по умолчанию - default branch)
        
        Returns:
            bytes: Содержимое zip-архива или None
        """
        # GitLab API для скачивания архива
        endpoint = f"{self._base_url}/repository/archive.zip"
        params = {}
        if ref:
            params['sha'] = ref
        
        try:
            print(f"🚚 Загрузка zip-архива для {self._project_path}...")
            response = requests.get(endpoint, headers=self._headers, params=params, stream=True)
            response.raise_for_status()
            content = response.content
            print(f"✅ Архив успешно загружен ({len(content)} байт)")
            return content
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Ошибка при скачивании архива: {e}")
            return None


def create_client(platform: str, token: str, repo_owner: str, repo_name: str, 
                  gitlab_url: str = "https://gitlab.com"):
    """
    Фабричный метод для создания клиента нужной платформы.
    
    Args:
        platform: "github" или "gitlab"
        token: Access token
        repo_owner: Владелец репозитория
        repo_name: Имя репозитория
        gitlab_url: URL GitLab сервера (только для GitLab)
    
    Returns:
        GitHubClient или GitLabClient
    """
    if platform.lower() == "gitlab":
        return GitLabClient(token, repo_owner, repo_name, gitlab_url)
    else:
        from .github_client import GitHubClient
        return GitHubClient(token, repo_owner, repo_name)
