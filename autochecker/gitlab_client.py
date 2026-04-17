# autochecker/gitlab_client.py
"""
Client for interacting with GitLab REST API.
Similar to github_client.py but for GitLab.
"""
import requests
import json
import hashlib
import sys
import io
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure stdout uses UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE_DIR = Path(".autochecker_cache")


class GitLabClient:
    """
    Client for interacting with GitLab REST API.
    Implements disk-based API response caching.

    Supports both gitlab.com and self-hosted GitLab.
    """

    def __init__(self, token: str, repo_owner: str, repo_name: str, gitlab_url: str = "https://gitlab.com", use_cache: bool = False):
        """
        Args:
            token: GitLab Personal Access Token (PAT) or Project Access Token
            repo_owner: Project owner (username or group)
            repo_name: Project name
            gitlab_url: GitLab server URL (default: gitlab.com)
            use_cache: Whether to use request caching
        """
        self._owner = repo_owner
        self._repo_name = repo_name
        self._gitlab_url = gitlab_url.rstrip('/')
        self._use_cache = use_cache
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

        # GitLab uses project_id in format "owner%2Frepo_name" (URL-encoded)
        self._project_path = f"{repo_owner}/{repo_name}"
        self._project_id = urllib.parse.quote(self._project_path, safe='')

        self._headers = {
            "PRIVATE-TOKEN": token,
            "Accept": "application/json"
        }
        self._base_url = f"{self._gitlab_url}/api/v4/projects/{self._project_id}"
        cache_status = "ON" if use_cache else "OFF"
        print(f"Initialized GitLabClient for project: {self._project_path} (Cache: {cache_status})")

    def _get_cached(self, endpoint: str) -> Optional[Any]:
        """Tries to get response from cache."""
        if not self._use_cache:
            return None

        cache_key = hashlib.md5(f"gitlab_{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        if cache_file.exists():
            print(f"  CACHE HIT: {endpoint}")
            with open(cache_file, "r") as f:
                return json.load(f)
        print(f"  CACHE MISS: {endpoint}")
        return None

    def _set_cache(self, endpoint: str, data: Any):
        """Saves response to cache."""
        if not self._use_cache:
            return

        cache_key = hashlib.md5(f"gitlab_{self._base_url}/{endpoint}".encode()).hexdigest()
        cache_file = CACHE_DIR / cache_key
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def _get(self, endpoint: str, use_cache: Optional[bool] = None, params: Dict = None) -> Optional[Any]:
        """Performs a GET request with caching support."""
        full_endpoint_url = self._base_url
        if endpoint:
            full_endpoint_url += f"/{endpoint}"

        # Add params to URL for cache key
        cache_key_url = full_endpoint_url
        if params:
            cache_key_url += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

        # If use_cache not explicitly passed, use instance setting
        should_cache = self._use_cache if use_cache is None else use_cache

        if should_cache:
            cached_data = self._get_cached(cache_key_url)
            if cached_data:
                return cached_data

        try:
            response = requests.get(full_endpoint_url, headers=self._headers, params=params)
            response.raise_for_status()
            data = response.json()
            if should_cache:
                self._set_cache(cache_key_url, data)
            return data
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            if status_code == 404:
                print(f"  Project not found: {self._project_path}")
                return None
            elif status_code == 401:
                print(f"  Authorization error (401). Check your GitLab token.")
                return None
            elif status_code == 403:
                print(f"  Access denied (403). Check token permissions.")
                return None
            else:
                print(f"  HTTP error {status_code} requesting {full_endpoint_url}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  Network error requesting {full_endpoint_url}: {e}")
            return None

    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Gets basic project info."""
        data = self._get("", use_cache=False)
        if data:
            # Convert GitLab format to GitHub-compatible
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
        Gets commit list for branch.
        Returns in GitHub-compatible format.
        """
        params = {'per_page': 100}
        if branch:
            params['ref_name'] = branch

        data = self._get("repository/commits", params=params) or []

        # Convert to GitHub-compatible format
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
        Gets all issues.
        Returns in GitHub-compatible format.
        """
        params = {'per_page': 100, 'state': 'all'}
        data = self._get("issues", params=params) or []

        # Convert to GitHub-compatible format
        issues = []
        for item in data:
            issues.append({
                'number': item.get('iid'),  # GitLab uses iid for project-level ID
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
        Gets all merge requests (analogous to pull requests in GitHub).
        Returns in GitHub-compatible format.
        """
        params = {'per_page': 100, 'state': 'all'}
        data = self._get("merge_requests", params=params) or []

        # Convert to GitHub-compatible format
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
        """Gets branch list."""
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
        """Gets branch protection info."""
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
        """Gets file content from repository."""
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
        Downloads repository as zip archive.

        Args:
            ref: Branch or commit to download (default: default branch)

        Returns:
            bytes: Zip archive content or None
        """
        # GitLab API for downloading archive
        endpoint = f"{self._base_url}/repository/archive.zip"
        params = {}
        if ref:
            params['sha'] = ref

        try:
            print(f"Downloading zip archive for {self._project_path}...")
            response = requests.get(endpoint, headers=self._headers, params=params, stream=True)
            response.raise_for_status()
            content = response.content
            print(f"Archive downloaded ({len(content)} bytes)")
            return content
        except requests.exceptions.RequestException as e:
            print(f"  Error downloading archive: {e}")
            return None


def create_client(platform: str, token: str, repo_owner: str, repo_name: str,
                  gitlab_url: str = "https://gitlab.com", use_cache: bool = False):
    """
    Factory method to create a client for the appropriate platform.

    Args:
        platform: "github" or "gitlab"
        token: Access token
        repo_owner: Repository owner
        repo_name: Repository name
        gitlab_url: GitLab server URL (GitLab only)
        use_cache: Whether to use caching

    Returns:
        GitHubClient or GitLabClient
    """
    if platform.lower() == "gitlab":
        return GitLabClient(token, repo_owner, repo_name, gitlab_url, use_cache=use_cache)
    else:
        from .github_client import GitHubClient
        return GitHubClient(token, repo_owner, repo_name, use_cache=use_cache)
