# autochecker/repo_reader.py
import requests
import zipfile
import io
from typing import Optional

class RepoReader:
    """
    Repository reader.
    Downloads repository zip archive into memory and provides methods
    for checking file existence and reading file content.

    Supports GitHub and GitLab.
    """
    def __init__(self, owner: str, repo_name: str, token: str, platform: str = "github",
                 gitlab_url: str = "https://gitlab.com", branch: Optional[str] = None):
        """
        Args:
            owner: Repository owner
            repo_name: Repository name
            token: Access token
            platform: "github" or "gitlab"
            gitlab_url: GitLab server URL (GitLab only)
            branch: Branch to download (default: default branch)
        """
        self._owner = owner
        self._repo_name = repo_name
        self._token = token
        self._platform = platform.lower()
        self._gitlab_url = gitlab_url.rstrip('/')
        self._branch = branch
        self._zip_file: Optional[zipfile.ZipFile] = None
        self._root_dir = ""
        self._download()

    def _download(self):
        """Downloads zipball into memory."""
        print(f"Downloading zip archive for {self._owner}/{self._repo_name}...")

        if self._platform == "gitlab":
            self._download_gitlab()
        else:
            self._download_github()

    def _download_github(self):
        """Downloads archive from GitHub."""
        # GitHub uses codeload.github.com for zipball with branch specification
        if self._branch:
            zip_url = f"https://codeload.github.com/{self._owner}/{self._repo_name}/zip/refs/heads/{self._branch}"
        else:
            zip_url = f"https://api.github.com/repos/{self._owner}/{self._repo_name}/zipball"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            response = requests.get(zip_url, headers=headers, stream=True)
            response.raise_for_status()
            self._zip_file = zipfile.ZipFile(io.BytesIO(response.content))
            self._root_dir = self._zip_file.namelist()[0]
            branch_info = f" (branch: {self._branch})" if self._branch else ""
            print(f"Archive downloaded into memory{branch_info}.")
        except requests.exceptions.RequestException as e:
            print(f"  Could not download archive: {e}")
        except zipfile.BadZipFile:
            print("  Downloaded file is not a valid zip archive.")
            self._zip_file = None

    def _download_gitlab(self):
        """Downloads archive from GitLab."""
        import urllib.parse
        project_id = urllib.parse.quote(f"{self._owner}/{self._repo_name}", safe='')
        zip_url = f"{self._gitlab_url}/api/v4/projects/{project_id}/repository/archive.zip"
        params = {}
        if self._branch:
            params['sha'] = self._branch
        headers = {"PRIVATE-TOKEN": self._token}
        try:
            response = requests.get(zip_url, headers=headers, params=params, stream=True)
            response.raise_for_status()
            self._zip_file = zipfile.ZipFile(io.BytesIO(response.content))
            namelist = self._zip_file.namelist()
            if namelist:
                self._root_dir = namelist[0]
                if not self._root_dir.endswith('/'):
                    for item in namelist:
                        if '/' in item:
                            self._root_dir = item.split('/')[0] + '/'
                            break
            branch_info = f" (branch: {self._branch})" if self._branch else ""
            print(f"Archive downloaded into memory{branch_info}.")
        except requests.exceptions.RequestException as e:
            print(f"  Could not download archive: {e}")
        except zipfile.BadZipFile:
            print("  Downloaded file is not a valid zip archive.")
            self._zip_file = None

    def file_exists(self, path: str) -> bool:
        """Checks if file exists in archive."""
        if not self._zip_file:
            return False

        path = path.lstrip('/')
        full_path = f"{self._root_dir}{path}"

        if full_path in self._zip_file.namelist():
            return True

        normalized_path = path.replace('\\', '/')
        for zip_path in self._zip_file.namelist():
            relative_path = zip_path.replace(self._root_dir, '')
            if relative_path == normalized_path or relative_path == path:
                return True

        return False

    def read_file(self, path: str) -> Optional[str]:
        """Reads file content from archive."""
        if not self.file_exists(path):
            return None

        path = path.lstrip('/')
        full_path = f"{self._root_dir}{path}"

        try:
            with self._zip_file.open(full_path) as f:
                return f.read().decode("utf-8")
        except KeyError:
            normalized_path = path.replace('\\', '/')
            for zip_path in self._zip_file.namelist():
                relative_path = zip_path.replace(self._root_dir, '')
                if relative_path == normalized_path or relative_path == path:
                    try:
                        with self._zip_file.open(zip_path) as f:
                            return f.read().decode("utf-8")
                    except:
                        pass
            return None
        except UnicodeDecodeError:
            return None

    def list_files(self, pattern: str = None):
        """Returns list of all files in repository."""
        if not self._zip_file:
            return []

        all_files = [f for f in self._zip_file.namelist()
                    if not f.endswith('/') and f.startswith(self._root_dir)]

        files = [f.replace(self._root_dir, '') for f in all_files]

        if pattern:
            import re
            files = [f for f in files if re.search(pattern, f)]

        return files

    @property
    def root_dir(self) -> str:
        """Returns root directory in archive."""
        return self._root_dir

    @property
    def platform(self) -> str:
        """Returns platform (github/gitlab)."""
        return self._platform
