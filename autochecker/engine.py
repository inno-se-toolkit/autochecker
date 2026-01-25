# autochecker/engine.py
import re
import fnmatch
from typing import List, Dict, Any, Optional, Tuple
from .github_client import GitHubClient
from .repo_reader import RepoReader

class CheckResult(Dict):
    id: str
    status: str # PASS, FAIL, ERROR
    description: str
    details: Optional[str]

class CheckEngine:
    """Движок, выполняющий проверки на основе данных."""
    def __init__(self, client: GitHubClient, reader: RepoReader, branch: Optional[str] = None):
        self._client = client
        self._reader = reader
        self._data_cache = {}
        self._branch = branch  # Branch to use (overrides repo default)

    def _get_commits(self):
        if 'commits' not in self._data_cache:
            repo_info = self._client.get_repo_info()
            if repo_info:
                # Use specified branch, or fall back to repo's default branch
                branch = self._branch or repo_info.get('default_branch', 'main')
                self._data_cache['commits'] = self._client.get_commits(branch)
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
    
    def check_glob_exists(self, patterns: List[str]) -> Tuple[bool, str]:
        """Проверяет существование файлов по glob паттернам."""
        all_files = self._reader.list_files() if hasattr(self._reader, 'list_files') else []
        if not all_files:
            return False, "Не удалось получить список файлов"
        
        matched_patterns = []
        unmatched_patterns = []
        
        for pattern in patterns:
            matched = False
            for file_path in all_files:
                if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(file_path, pattern.rstrip('*').rstrip('/')):
                    matched = True
                    break
                # Также проверяем наличие директории
                if pattern.endswith('/**') and file_path.startswith(pattern[:-3]):
                    matched = True
                    break
            
            if matched:
                matched_patterns.append(pattern)
            else:
                unmatched_patterns.append(pattern)
        
        passed = len(unmatched_patterns) == 0
        details = ""
        if matched_patterns:
            details += f"Найдены: {', '.join(matched_patterns)}\n"
        if unmatched_patterns:
            details += f"Не найдены: {', '.join(unmatched_patterns)}"
        
        return passed, details
    
    def check_markdown_sections_nonempty(self, path: str, headings: List[str]) -> Tuple[bool, str]:
        """Проверяет, что Markdown файл содержит указанные заголовки и они не пустые."""
        if not self._reader.file_exists(path):
            return False, f"Файл {path} не найден"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"Файл {path} пустой или недоступен"
        
        content_lower = content.lower()
        found_headings = []
        empty_headings = []
        missing_headings = []
        
        for heading in headings:
            heading_lower = heading.lower()
            # Ищем заголовок с любым уровнем (# ## ### ####)
            pattern = rf'^(#{1,6})\s*{re.escape(heading_lower)}\s*$'
            match = re.search(pattern, content_lower, re.MULTILINE | re.IGNORECASE)
            
            if match:
                # Находим позицию следующего заголовка
                start_pos = match.end()
                next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)
                
                if next_heading:
                    section_content = content[start_pos:start_pos + next_heading.start()]
                else:
                    section_content = content[start_pos:]
                
                # Проверяем, что секция не пустая (после удаления пробелов и переносов)
                section_text = section_content.strip()
                if len(section_text) > 10:  # Минимум 10 символов контента
                    found_headings.append(heading)
                else:
                    empty_headings.append(heading)
            else:
                missing_headings.append(heading)
        
        passed = len(missing_headings) == 0 and len(empty_headings) == 0
        
        details = []
        if found_headings:
            details.append(f"✅ Найдены секции: {', '.join(found_headings)}")
        if empty_headings:
            details.append(f"⚠️ Пустые секции: {', '.join(empty_headings)}")
        if missing_headings:
            details.append(f"❌ Отсутствуют секции: {', '.join(missing_headings)}")
        
        return passed, "\n".join(details)
    
    def check_markdown_regex_all(self, path: str, rules: Dict[str, Dict[str, str]]) -> Tuple[bool, str]:
        """Проверяет, что все регулярные выражения находят совпадения в файле."""
        if not self._reader.file_exists(path):
            return False, f"Файл {path} не найден"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"Файл {path} пустой"
        
        passed_rules = []
        failed_rules = []
        
        for rule_name, rule_config in rules.items():
            pattern = rule_config.get('pattern', '')
            if not pattern:
                continue
            
            try:
                match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                if match:
                    passed_rules.append(rule_name)
                else:
                    failed_rules.append(rule_name)
            except re.error as e:
                failed_rules.append(f"{rule_name} (ошибка regex: {e})")
        
        passed = len(failed_rules) == 0
        details = []
        if passed_rules:
            details.append(f"✅ Пройдены: {', '.join(passed_rules)}")
        if failed_rules:
            details.append(f"❌ Не пройдены: {', '.join(failed_rules)}")
        
        return passed, "\n".join(details)
    
    def check_markdown_linked_files_exist(self, md_path: str, allow_extensions: List[str], 
                                          validate_only_relative: bool = True) -> Tuple[bool, str]:
        """Проверяет, что файлы, на которые есть ссылки в Markdown, существуют."""
        if not self._reader.file_exists(md_path):
            return False, f"Файл {md_path} не найден"
        
        content = self._reader.read_file(md_path)
        if not content:
            return False, f"Файл {md_path} пустой"
        
        # Ищем все ссылки в формате [text](path) и src="path"
        link_patterns = [
            r'\[([^\]]*)\]\(([^)]+)\)',  # [text](path)
            r'src=["\']([^"\']+)["\']',   # src="path" or src='path'
        ]
        
        found_links = []
        for pattern in link_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # Для паттерна [text](path) берем второй элемент
                if isinstance(match, tuple):
                    link = match[-1]  # Последний элемент - путь
                else:
                    link = match
                found_links.append(link)
        
        # Фильтруем ссылки по расширениям
        filtered_links = []
        for link in found_links:
            # Пропускаем внешние ссылки
            if link.startswith('http://') or link.startswith('https://'):
                continue
            # Пропускаем якоря
            if link.startswith('#'):
                continue
            # Проверяем расширение
            for ext in allow_extensions:
                if link.lower().endswith(ext.lower()):
                    filtered_links.append(link)
                    break
        
        # Проверяем существование файлов
        existing_files = []
        missing_files = []
        
        # Получаем директорию Markdown файла для относительных путей
        import os
        md_dir = os.path.dirname(md_path)
        
        for link in filtered_links:
            # Нормализуем путь
            if link.startswith('./'):
                link = link[2:]
            
            # Строим полный путь относительно Markdown файла
            full_path = os.path.normpath(os.path.join(md_dir, link))
            
            if self._reader.file_exists(full_path):
                existing_files.append(link)
            else:
                missing_files.append(link)
        
        passed = len(missing_files) == 0
        details = []
        if existing_files:
            details.append(f"✅ Найдены: {len(existing_files)} файлов")
        if missing_files:
            details.append(f"❌ Не найдены: {', '.join(missing_files[:5])}")
        
        return passed, "\n".join(details)
    
    def check_markdown_section_item_count(self, path: str, heading: str, 
                                          min_items: int, item_kinds: List[str]) -> Tuple[bool, str]:
        """Проверяет количество элементов в секции Markdown."""
        if not self._reader.file_exists(path):
            return False, f"Файл {path} не найден"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"Файл {path} пустой"
        
        # Находим секцию
        heading_pattern = rf'^(#{1,6})\s*{re.escape(heading)}\s*$'
        match = re.search(heading_pattern, content, re.MULTILINE | re.IGNORECASE)
        
        if not match:
            return False, f"Секция '{heading}' не найдена"
        
        # Получаем контент секции
        start_pos = match.end()
        next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)
        
        if next_heading:
            section_content = content[start_pos:start_pos + next_heading.start()]
        else:
            section_content = content[start_pos:]
        
        # Подсчитываем элементы
        item_count = 0
        
        if "bullet" in item_kinds:
            # Считаем маркированные списки (- или *)
            bullets = re.findall(r'^[\s]*[-*]\s+.+$', section_content, re.MULTILINE)
            item_count += len(bullets)
        
        if "numbered" in item_kinds:
            # Считаем нумерованные списки
            numbered = re.findall(r'^[\s]*\d+\.\s+.+$', section_content, re.MULTILINE)
            item_count += len(numbered)
        
        if "nonempty_line" in item_kinds and item_count == 0:
            # Считаем непустые строки (если не нашли списки)
            lines = [line for line in section_content.split('\n') if line.strip()]
            item_count = len(lines)
        
        passed = item_count >= min_items
        details = f"Найдено элементов: {item_count}, требуется: {min_items}"
        
        return passed, details
    
    def check_urls_in_markdown_section_min(self, path: str, heading: str, min_count: int) -> Tuple[bool, str]:
        """Проверяет минимальное количество URL в секции Markdown."""
        if not self._reader.file_exists(path):
            return False, f"Файл {path} не найден"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"Файл {path} пустой"
        
        # Находим секцию
        heading_pattern = rf'^(#{1,6})\s*{re.escape(heading)}\s*$'
        match = re.search(heading_pattern, content, re.MULTILINE | re.IGNORECASE)
        
        if not match:
            return False, f"Секция '{heading}' не найдена"
        
        # Получаем контент секции
        start_pos = match.end()
        next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)
        
        if next_heading:
            section_content = content[start_pos:start_pos + next_heading.start()]
        else:
            section_content = content[start_pos:]
        
        # Ищем URL
        url_pattern = r'https?://[^\s<>\[\]()\'\"]+[^\s<>\[\]()\'\".,;:!?]'
        urls = re.findall(url_pattern, section_content, re.IGNORECASE)
        
        # Фильтруем плейсхолдеры
        placeholder_patterns = [r'example\.com', r'your[-_]?link', r'placeholder']
        valid_urls = [url for url in urls if not any(re.search(p, url.lower()) for p in placeholder_patterns)]
        
        passed = len(valid_urls) >= min_count
        details = f"Найдено ссылок: {len(valid_urls)}, требуется: {min_count}"
        
        return passed, details
    
    def check_pr_body_regex_count(self, base: str, merged: bool, pattern: str, min_prs: int) -> Tuple[bool, str]:
        """Проверяет количество PR с паттерном в теле."""
        prs = self._get_prs()
        
        # Фильтруем PR по базовой ветке и статусу
        filtered_prs = []
        for pr in prs:
            if merged and not pr.get('merged_at'):
                continue
            if pr.get('base', {}).get('ref') != base:
                continue
            filtered_prs.append(pr)
        
        # Проверяем тело PR на паттерн
        matching_prs = 0
        for pr in filtered_prs:
            body = pr.get('body', '') or ''
            if re.search(pattern, body, re.IGNORECASE):
                matching_prs += 1
        
        passed = matching_prs >= min_prs
        details = f"PR с паттерном: {matching_prs}, требуется: {min_prs}"
        
        return passed, details
    
    def check_pr_review_approvals(self, base: str, min_total_approvals: int) -> Tuple[bool, str]:
        """Проверяет количество approvals в PR reviews."""
        prs = self._get_prs()
        
        total_approvals = 0
        for pr in prs:
            if pr.get('base', {}).get('ref') != base:
                continue
            
            # Получаем reviews для PR
            pr_number = pr.get('number')
            if pr_number:
                reviews = self._client.get_pr_reviews(pr_number) if hasattr(self._client, 'get_pr_reviews') else []
                for review in reviews:
                    if review.get('state') == 'APPROVED':
                        total_approvals += 1
        
        passed = total_approvals >= min_total_approvals
        details = f"Всего approvals: {total_approvals}, требуется: {min_total_approvals}"
        
        return passed, details
    
    def check_pr_review_line_comments(self, base: str, min_total_line_comments: int) -> Tuple[bool, str]:
        """Проверяет количество line comments в PR reviews."""
        prs = self._get_prs()
        
        total_comments = 0
        for pr in prs:
            if pr.get('base', {}).get('ref') != base:
                continue
            
            pr_number = pr.get('number')
            if pr_number:
                comments = self._client.get_pr_review_comments(pr_number) if hasattr(self._client, 'get_pr_review_comments') else []
                total_comments += len(comments)
        
        passed = total_comments >= min_total_line_comments
        details = f"Всего line comments: {total_comments}, требуется: {min_total_line_comments}"
        
        return passed, details
    
    def check_issue_exists(self, title_regex: str, state: str = "all") -> Tuple[bool, str]:
        """Проверяет существование Issue с заданным паттерном."""
        issues = self._get_issues()
        
        for issue in issues:
            if state != "all" and issue.get('state') != state:
                continue
            if re.search(title_regex, issue.get('title', ''), re.IGNORECASE):
                return True, f"Найдена Issue: {issue.get('title')}"
        
        return False, f"Issue с паттерном '{title_regex}' не найдена"
    
    def check_commit_message_regex_count(self, pattern: str, min_count: int) -> Tuple[bool, str]:
        """Проверяет количество коммитов, соответствующих паттерну."""
        commits = self._get_commits()
        
        matching_commits = 0
        for commit in commits:
            message = commit.get('commit', {}).get('message', '')
            if re.match(pattern, message):
                matching_commits += 1
        
        passed = matching_commits >= min_count
        details = f"Коммитов с паттерном: {matching_commits}, требуется: {min_count}"
        
        return passed, details

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
            
            elif check_type == "glob_exists":
                patterns = params.get('patterns', [])
                passed, details = self.check_glob_exists(patterns)
                if passed: status = "PASS"
            
            elif check_type == "markdown_sections_nonempty":
                path = params.get('path', '')
                headings = params.get('headings', [])
                passed, details = self.check_markdown_sections_nonempty(path, headings)
                if passed: status = "PASS"
            
            elif check_type == "markdown_regex_all":
                path = params.get('path', '')
                rules = params.get('rules', {})
                passed, details = self.check_markdown_regex_all(path, rules)
                if passed: status = "PASS"
            
            elif check_type == "markdown_linked_files_exist":
                md_path = params.get('md_path', '')
                allow_extensions = params.get('allow_extensions', [])
                validate_only_relative = params.get('validate_only_relative', True)
                passed, details = self.check_markdown_linked_files_exist(md_path, allow_extensions, validate_only_relative)
                if passed: status = "PASS"
            
            elif check_type == "markdown_section_item_count":
                path = params.get('path', '')
                heading = params.get('heading', '')
                min_items = params.get('min_items', 1)
                item_kinds = params.get('item_kinds', ['bullet', 'numbered'])
                passed, details = self.check_markdown_section_item_count(path, heading, min_items, item_kinds)
                if passed: status = "PASS"
            
            elif check_type == "urls_in_markdown_section_min":
                path = params.get('path', '')
                heading = params.get('heading', '')
                min_count = params.get('min', 1)
                passed, details = self.check_urls_in_markdown_section_min(path, heading, min_count)
                if passed: status = "PASS"
            
            elif check_type == "commit_message_regex":
                pattern = params.get('pattern', '')
                min_count = params.get('min_count', 0)
                if min_count > 0:
                    passed, details = self.check_commit_message_regex_count(pattern, min_count)
                    if passed: status = "PASS"
                else:
                    if self.check_commit_message_regex(pattern): status = "PASS"
            
            elif check_type == "issues_count":
                title_regex = params.get('title_regex', '')
                min_count = params.get('min', params.get('min_count', 0))
                state = params.get('state', 'all')
                if self.check_issues_count(title_regex, min_count): status = "PASS"
            
            elif check_type == "issue_exists":
                title_regex = params.get('title_regex', '')
                state = params.get('state', 'all')
                passed, details = self.check_issue_exists(title_regex, state)
                if passed: status = "PASS"
            
            elif check_type == "pr_merged_count":
                min_count = params.get('min', params.get('min_count', 0))
                if self.check_pr_merged_count(min_count): status = "PASS"
            
            elif check_type == "pr_body_regex_count":
                base = params.get('base', 'main')
                merged = params.get('merged', True)
                pattern = params.get('pattern', '')
                min_prs = params.get('min_prs', 1)
                passed, details = self.check_pr_body_regex_count(base, merged, pattern, min_prs)
                if passed: status = "PASS"
            
            elif check_type == "pr_review_approvals":
                base = params.get('base', 'main')
                min_total_approvals = params.get('min_total_approvals', 1)
                passed, details = self.check_pr_review_approvals(base, min_total_approvals)
                if passed: status = "PASS"
            
            elif check_type == "pr_review_line_comments":
                base = params.get('base', 'main')
                min_total_line_comments = params.get('min_total_line_comments', 1)
                passed, details = self.check_pr_review_line_comments(base, min_total_line_comments)
                if passed: status = "PASS"
            
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
            
            elif check_type == "llm_judge":
                # LLM проверки обрабатываются отдельно, не через engine
                status = "SKIP"
                details = "LLM проверка выполняется отдельно"
            
            else:
                # Неподдерживаемые типы проверок
                status = "ERROR"
                unsupported_checks = {
                    "branch_protection_enabled": "Проверка защиты веток не реализована. Требуется доступ к GitHub API для Branch Rulesets.",
                    "or_check": "Составная проверка (OR) не реализована.",
                    "file_min_bytes": "Проверка минимального размера файла не реализована.",
                    "pr_links_issue": "Проверка связи PR с Issues не реализована.",
                }
                details = unsupported_checks.get(
                    check_type, 
                    f"Тип проверки '{check_type}' не реализован. Пожалуйста, добавьте реализацию в engine.py"
                )

        except Exception as e:
            status = "ERROR"
            details = f"Ошибка при выполнении проверки '{check_id}': {e}"
        
        return CheckResult(id=check_id, status=status, details=details, description=description)
