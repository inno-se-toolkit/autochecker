# autochecker/engine.py
import re
from typing import List, Dict, Any, Optional
from .github_client import GitHubClient
from .repo_reader import RepoReader

class CheckResult(Dict):
    id: str
    status: str # PASS, FAIL, ERROR
    description: str
    details: Optional[str]

class CheckEngine:
    """Движок, выполняющий проверки на основе данных."""
    def __init__(self, client: GitHubClient, reader: RepoReader):
        self._client = client
        self._reader = reader
        self._data_cache = {}

    def _get_commits(self):
        if 'commits' not in self._data_cache:
            repo_info = self._client.get_repo_info()
            if repo_info:
                self._data_cache['commits'] = self._client.get_commits(repo_info['default_branch'])
            else:
                self._data_cache['commits'] = []
        return self._data_cache['commits']
    
    def _get_issues(self):
        if 'issues' not in self._data_cache:
            self._data_cache['issues'] = self._client.get_issues()
        return self._data_cache['issues']
    
    def _get_prs(self):
        if 'prs' not in self._data_cache:
            self._data_cache['prs'] = self._client.get_pull_requests()
        return self._data_cache['prs']

    # --- Примитивы проверок ---

    def check_repo_exists(self) -> bool:
        return self._client.get_repo_info() is not None

    def check_file_exists(self, path: str) -> bool:
        return self._reader.file_exists(path)

    def check_commit_message_regex(self, pattern: str) -> bool:
        commits = self._get_commits()
        if not commits:
            return False
        # Проверяем, что ВСЕ коммиты соответствуют паттерну
        for commit in commits:
            if not re.match(pattern, commit['commit']['message']):
                return False
        return True

    def check_issues_count(self, title_regex: str, min_count: int) -> bool:
        issues = self._get_issues()
        count = 0
        for issue in issues:
            # Используем search вместо match для более гибкого поиска
            if re.search(title_regex, issue['title']):
                count += 1
        return count >= min_count

    def check_pr_merged_count(self, min_count: int) -> bool:
        prs = self._get_prs()
        count = sum(1 for pr in prs if pr.get('merged_at'))
        return count >= min_count
    
    def check_file_content_match(self, path: str, must_contain: List[str]) -> bool:
        """Проверяет, что файл содержит указанные ключевые слова/фразы."""
        # Сначала проверяем, что файл существует
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        content_lower = content.lower()
        # Проверяем, что все требуемые фразы присутствуют
        for phrase in must_contain:
            if phrase.lower() not in content_lower:
                return False
        return True
    
    def check_file_word_count(self, path: str, min_words: int) -> bool:
        """Проверяет, что файл содержит минимум указанное количество слов."""
        # Сначала проверяем, что файл существует
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        # Подсчитываем слова (разделяем по пробелам и переносам строк)
        words = content.split()
        return len(words) >= min_words
    
    def check_markdown_has_headings(self, path: str, headings: List[str]) -> bool:
        """Проверяет, что Markdown файл содержит указанные заголовки."""
        # Сначала проверяем, что файл существует
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        content_lower = content.lower()
        # Ищем заголовки в формате #, ##, ### и т.д.
        for heading in headings:
            heading_lower = heading.lower()
            # Проверяем разные форматы заголовков
            patterns = [
                f"# {heading_lower}",
                f"## {heading_lower}",
                f"### {heading_lower}",
                f"#### {heading_lower}",
            ]
            found = any(pattern in content_lower for pattern in patterns)
            if not found:
                return False
        return True
    
    def check_regex_in_file(self, path: str, pattern: str, min_matches: int = 1) -> bool:
        """Проверяет, что в файле есть совпадения с регулярным выражением."""
        # Сначала проверяем, что файл существует
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        return len(matches) >= min_matches
    
    def check_issue_body_match(self, body_regex: str, min_count: int) -> bool:
        """Проверяет, что Issues содержат указанный паттерн в теле."""
        issues = self._get_issues()
        count = 0
        for issue in issues:
            body = issue.get('body', '') or ''
            if re.search(body_regex, body, re.IGNORECASE):
                count += 1
        return count >= min_count
    
    def check_links_in_file(self, path: str, link_type: str, min_count: int = 1) -> Dict[str, Any]:
        """
        Проверяет ссылки в файле на подлинность и релевантность.
        
        Args:
            path: Путь к файлу
            link_type: Тип ссылок для проверки:
                - "job" - ссылки на вакансии (hh.ru, linkedin, etc.)
                - "any" - любые HTTP/HTTPS ссылки
                - "github" - ссылки на GitHub
            min_count: Минимальное количество валидных ссылок
        
        Returns:
            Dict с result (bool) и details (str)
        """
        if not self._reader.file_exists(path):
            return {"result": False, "details": "Файл не найден"}
        
        content = self._reader.read_file(path)
        if not content:
            return {"result": False, "details": "Файл пустой или недоступен"}
        
        # Паттерны для поиска ссылок
        url_pattern = r'https?://[^\s<>\[\]()\'\"]+[^\s<>\[\]()\'\".,;:!?]'
        
        # Шаблоны-плейсхолдеры, которые считаются невалидными
        placeholder_patterns = [
            r'example\.com',
            r'your[-_]?link',
            r'<your[-_]',
            r'\[link\]',
            r'\[your[-_]',
            r'username',
            r'repo[-_]?name',
            r'placeholder',
            r'xxx+',
            r'sample\.com',
            r'test\.com',
        ]
        
        # Домены для разных типов ссылок
        job_domains = [
            'hh.ru', 'hh.kz', 'headhunter',
            'linkedin.com/jobs', 'linkedin.com/in',
            'indeed.com', 'glassdoor.com',
            'career', 'jobs.', 'vacancy', 'vacancies',
            'work.ua', 'rabota.', 'superjob',
        ]
        
        github_domains = ['github.com', 'gitlab.com', 'bitbucket.org']
        
        # Находим все ссылки
        all_urls = re.findall(url_pattern, content, re.IGNORECASE)
        
        valid_links = []
        invalid_links = []
        
        for url in all_urls:
            url_lower = url.lower()
            
            # Проверяем на плейсхолдеры
            is_placeholder = any(re.search(p, url_lower) for p in placeholder_patterns)
            if is_placeholder:
                invalid_links.append(f"❌ {url[:60]}... - плейсхолдер")
                continue
            
            # Проверяем на generic ссылки (только домен без пути)
            # Паттерн: https://domain.com или https://domain.com/
            is_generic = re.match(r'^https?://[^/]+/?$', url)
            if is_generic and link_type != "any":
                invalid_links.append(f"❌ {url} - только домен, нет конкретной страницы")
                continue
            
            # Проверяем соответствие типу
            if link_type == "job":
                is_job_link = any(domain in url_lower for domain in job_domains)
                if is_job_link:
                    valid_links.append(url)
                # Не добавляем в invalid, т.к. это может быть другой тип ссылки
            elif link_type == "github":
                is_github_link = any(domain in url_lower for domain in github_domains)
                if is_github_link:
                    valid_links.append(url)
            else:  # any
                valid_links.append(url)
        
        passed = len(valid_links) >= min_count
        
        details = ""
        if valid_links:
            details += f"Найдено валидных ссылок: {len(valid_links)}\n"
        if invalid_links:
            details += f"Невалидные ссылки:\n" + "\n".join(invalid_links[:5])
        
        return {
            "result": passed,
            "details": details,
            "valid_count": len(valid_links),
            "invalid_count": len(invalid_links)
        }

    def run_check(self, check_id: str, check_type: str, params: Dict[str, Any], description: str = "") -> CheckResult:
        """Запускает одну проверку по ее типу."""
        status = "FAIL"
        details = ""
        try:
            if check_type == "repo_exists":
                if self.check_repo_exists(): status = "PASS"
            elif check_type == "file_exists":
                path = params.get('path', '')
                if self.check_file_exists(path): status = "PASS"
            elif check_type == "commit_message_regex":
                pattern = params.get('pattern', '')
                if self.check_commit_message_regex(pattern): status = "PASS"
            elif check_type == "issues_count":
                title_regex = params.get('title_regex', '')
                min_count = params.get('min', params.get('min_count', 0))
                if self.check_issues_count(title_regex, min_count): status = "PASS"
            elif check_type == "pr_merged_count":
                min_count = params.get('min', params.get('min_count', 0))
                if self.check_pr_merged_count(min_count): status = "PASS"
            elif check_type == "file_content_match":
                path = params.get('path', '')
                must_contain = params.get('must_contain', [])
                if self.check_file_content_match(path, must_contain): status = "PASS"
            elif check_type == "file_word_count":
                path = params.get('path', '')
                min_words = params.get('min_words', 0)
                if self.check_file_word_count(path, min_words): status = "PASS"
            elif check_type == "markdown_has_heading":
                path = params.get('path', '')
                headings = params.get('headings', [])
                if self.check_markdown_has_headings(path, headings): status = "PASS"
            elif check_type == "regex_in_file":
                path = params.get('path', '')
                pattern = params.get('pattern', '')
                min_matches = params.get('min_matches', 1)
                if self.check_regex_in_file(path, pattern, min_matches): status = "PASS"
            elif check_type == "issue_body_match":
                body_regex = params.get('body_regex', '')
                min_count = params.get('min_count', 0)
                if self.check_issue_body_match(body_regex, min_count): status = "PASS"
            elif check_type == "links_in_file":
                path = params.get('path', '')
                link_type = params.get('link_type', 'any')
                min_count = params.get('min_count', 1)
                result = self.check_links_in_file(path, link_type, min_count)
                if result['result']: 
                    status = "PASS"
                details = result.get('details', '')
            else:
                # Неподдерживаемые типы проверок
                status = "ERROR"
                unsupported_checks = {
                    "branch_protection_enabled": "Проверка защиты веток не реализована. Требуется доступ к GitHub API для Branch Rulesets.",
                    "or_check": "Составная проверка (OR) не реализована.",
                    "glob_exists": "Проверка файлов по шаблону (glob) не реализована.",
                    "file_min_bytes": "Проверка минимального размера файла не реализована.",
                    "pr_links_issue": "Проверка связи PR с Issues не реализована.",
                    "pr_review_approvals": "Проверка Code Review и Approvals не реализована.",
                }
                details = unsupported_checks.get(
                    check_type, 
                    f"Тип проверки '{check_type}' не реализован. Пожалуйста, добавьте реализацию в engine.py"
                )

        except Exception as e:
            status = "ERROR"
            details = f"Ошибка при выполнении проверки '{check_id}': {e}"
        
        return CheckResult(id=check_id, status=status, details=details, description=description)
