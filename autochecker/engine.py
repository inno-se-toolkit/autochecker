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
    hint: Optional[str]

class CheckEngine:
    """Engine that runs data-based checks."""
    def __init__(self, client: GitHubClient, reader: RepoReader, branch: Optional[str] = None, lab_spec: Optional[Any] = None):
        self._client = client
        self._reader = reader
        self._branch = branch
        self._lab_spec = lab_spec
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

    # --- Check primitives ---

    def check_repo_exists(self) -> bool:
        return self._client.get_repo_info() is not None

    def check_repo_is_fork(self) -> bool:
        repo_info = self._client.get_repo_info()
        return repo_info is not None and repo_info.get('fork', False)

    def check_repo_has_issues(self) -> bool:
        repo_info = self._client.get_repo_info()
        return repo_info is not None and repo_info.get('has_issues', False)

    def check_file_exists(self, path: str) -> bool:
        return self._reader.file_exists(path)

    def check_commit_message_regex(self, pattern: str) -> bool:
        commits = self._get_commits()
        if not commits:
            return False
        # Check that ANY commit matches the pattern
        for commit in commits:
            if re.search(pattern, commit['commit']['message']):
                return True
        return False

    def check_issues_count(self, title_regex: str, min_count: int) -> bool:
        issues = self._get_issues()
        count = 0
        for issue in issues:
            # Use search instead of match for flexible matching
            if re.search(title_regex, issue['title']):
                count += 1
        return count >= min_count

    def check_pr_merged_count(self, min_count: int) -> bool:
        prs = self._get_prs()
        count = sum(1 for pr in prs if pr.get('merged_at'))
        return count >= min_count
    
    def check_file_content_match(self, path: str, must_contain: List[str]) -> bool:
        """Checks that the file contains the specified keywords/phrases."""
        # First check that the file exists
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        content_lower = content.lower()
        # Check that all required phrases are present
        for phrase in must_contain:
            if phrase.lower() not in content_lower:
                return False
        return True
    
    def check_file_word_count(self, path: str, min_words: int) -> bool:
        """Checks that the file contains at least the specified number of words."""
        # First check that the file exists
        if not self._reader.file_exists(path):
            return False

        content = self._reader.read_file(path)
        if not content:
            return False

        # Count words (split by whitespace and newlines)
        words = content.split()
        return len(words) >= min_words
    
    def check_markdown_has_headings(self, path: str, headings: List[str]) -> bool:
        """Checks that the Markdown file contains the specified headings."""
        # First check that the file exists
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        content_lower = content.lower()
        # Search for headings in #, ##, ### etc. format
        for heading in headings:
            heading_lower = heading.lower()
            # Check different heading formats
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
        """Checks that the file has matches for the regular expression."""
        # First check that the file exists
        if not self._reader.file_exists(path):
            return False
        
        content = self._reader.read_file(path)
        if not content:
            return False
        
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        return len(matches) >= min_matches
    
    def check_issue_body_match(self, body_regex: str, min_count: int) -> bool:
        """Checks that issues contain the specified pattern in their body."""
        issues = self._get_issues()
        count = 0
        for issue in issues:
            body = issue.get('body', '') or ''
            if re.search(body_regex, body, re.IGNORECASE):
                count += 1
        return count >= min_count
    
    def check_links_in_file(self, path: str, link_type: str, min_count: int = 1) -> Dict[str, Any]:
        """
        Checks links in a file for authenticity and relevance.

        Args:
            path: Path to the file
            link_type: Type of links to check:
                - "job" - job posting links (hh.ru, linkedin, etc.)
                - "any" - any HTTP/HTTPS links
                - "github" - GitHub links
            min_count: Minimum number of valid links

        Returns:
            Dict with result (bool) and details (str)
        """
        if not self._reader.file_exists(path):
            return {"result": False, "details": "File not found"}
        
        content = self._reader.read_file(path)
        if not content:
            return {"result": False, "details": "File is empty or inaccessible"}
        
        # Patterns for finding links
        url_pattern = r'https?://[^\s<>\[\]()\'\"]+[^\s<>\[\]()\'\".,;:!?]'
        
        # Placeholder patterns that are considered invalid
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
        
        # Domains for different link types
        job_domains = [
            'hh.ru', 'hh.kz', 'headhunter',
            'linkedin.com/jobs', 'linkedin.com/in',
            'indeed.com', 'glassdoor.com',
            'career', 'jobs.', 'vacancy', 'vacancies',
            'work.ua', 'rabota.', 'superjob',
        ]
        
        github_domains = ['github.com', 'gitlab.com', 'bitbucket.org']
        
        # Find all links
        all_urls = re.findall(url_pattern, content, re.IGNORECASE)
        
        valid_links = []
        invalid_links = []
        
        for url in all_urls:
            url_lower = url.lower()
            
            # Check for placeholders
            is_placeholder = any(re.search(p, url_lower) for p in placeholder_patterns)
            if is_placeholder:
                invalid_links.append(f"❌ {url[:60]}... - placeholder")
                continue
            
            # Check for generic links (domain only, no path)
            # Pattern: https://domain.com or https://domain.com/
            is_generic = re.match(r'^https?://[^/]+/?$', url)
            if is_generic and link_type != "any":
                invalid_links.append(f"❌ {url} - domain only, no specific page")
                continue
            
            # Check type match
            if link_type == "job":
                is_job_link = any(domain in url_lower for domain in job_domains)
                if is_job_link:
                    valid_links.append(url)
                # Don't add to invalid, as it may be a different link type
            elif link_type == "github":
                is_github_link = any(domain in url_lower for domain in github_domains)
                if is_github_link:
                    valid_links.append(url)
            else:  # any
                valid_links.append(url)
        
        passed = len(valid_links) >= min_count
        
        details = ""
        if valid_links:
            details += f"Valid links found: {len(valid_links)}\n"
        if invalid_links:
            details += f"Invalid links:\n" + "\n".join(invalid_links[:5])
        
        return {
            "result": passed,
            "details": details,
            "valid_count": len(valid_links),
            "invalid_count": len(invalid_links)
        }
    
    def check_glob_exists(self, patterns: List[str]) -> Tuple[bool, str]:
        """Checks file existence by glob patterns."""
        all_files = self._reader.list_files() if hasattr(self._reader, 'list_files') else []
        if not all_files:
            return False, "Could not get file list"
        
        matched_patterns = []
        unmatched_patterns = []
        
        for pattern in patterns:
            matched = False
            for file_path in all_files:
                if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(file_path, pattern.rstrip('*').rstrip('/')):
                    matched = True
                    break
                # Also check for directory existence
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
            details += f"Found: {', '.join(matched_patterns)}\n"
        if unmatched_patterns:
            details += f"Not found: {', '.join(unmatched_patterns)}"
        
        return passed, details
    
    def check_markdown_sections_nonempty(self, path: str, headings: List[str]) -> Tuple[bool, str]:
        """Checks that the Markdown file contains the specified headings and they are not empty."""
        if not self._reader.file_exists(path):
            return False, f"File {path} not found"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"File {path} is empty or inaccessible"
        
        content_lower = content.lower()
        found_headings = []
        empty_headings = []
        missing_headings = []
        
        for heading in headings:
            heading_lower = heading.lower()
            # Search for heading at any level (# ## ### ####)
            pattern = rf'^(#{{1,6}})\s*{re.escape(heading_lower)}[.!?]?\s*$'
            match = re.search(pattern, content_lower, re.MULTILINE | re.IGNORECASE)
            
            if match:
                # Find the position of the next heading
                start_pos = match.end()
                next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)
                
                if next_heading:
                    section_content = content[start_pos:start_pos + next_heading.start()]
                else:
                    section_content = content[start_pos:]
                
                # Check that the section is not empty (after stripping whitespace and newlines)
                section_text = section_content.strip()
                if len(section_text) > 10:  # Minimum 10 characters of content
                    found_headings.append(heading)
                else:
                    empty_headings.append(heading)
            else:
                missing_headings.append(heading)
        
        passed = len(missing_headings) == 0 and len(empty_headings) == 0
        
        details = []
        if found_headings:
            details.append(f"✅ Found sections: {', '.join(found_headings)}")
        if empty_headings:
            details.append(f"⚠️ Empty sections: {', '.join(empty_headings)}")
        if missing_headings:
            details.append(f"❌ Missing sections: {', '.join(missing_headings)}")
        
        return passed, "\n".join(details)
    
    def check_markdown_regex_all(self, path: str, rules: Dict[str, Dict[str, str]]) -> Tuple[bool, str]:
        """Checks that all regular expressions find matches in the file."""
        if not self._reader.file_exists(path):
            return False, f"File {path} not found"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"File {path} is empty"
        
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
                failed_rules.append(f"{rule_name} (regex error: {e})")
        
        passed = len(failed_rules) == 0
        details = []
        if passed_rules:
            details.append(f"✅ Passed: {', '.join(passed_rules)}")
        if failed_rules:
            details.append(f"❌ Not passed: {', '.join(failed_rules)}")
        
        return passed, "\n".join(details)
    
    def check_markdown_linked_files_exist(self, md_path: str, allow_extensions: List[str],
                                          validate_only_relative: bool = True) -> Tuple[bool, str]:
        """Checks that files referenced by links in the Markdown file exist."""
        from urllib.parse import unquote
        if not self._reader.file_exists(md_path):
            return False, f"File {md_path} not found"

        content = self._reader.read_file(md_path)
        if not content:
            return False, f"File {md_path} is empty"

        # Find all links in [text](path) and src="path" format
        link_patterns = [
            r'\[([^\]]*)\]\(([^)]+)\)',  # [text](path)
            r'src=["\']([^"\']+)["\']',   # src="path" or src='path'
        ]

        found_links = []
        for pattern in link_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # For [text](path) pattern, take the second element
                if isinstance(match, tuple):
                    link = match[-1]  # Last element is the path
                else:
                    link = match
                found_links.append(link)

        # Filter links by extensions
        filtered_links = []
        for link in found_links:
            # Skip external links
            if link.startswith('http://') or link.startswith('https://'):
                continue
            # Skip anchors
            if link.startswith('#'):
                continue
            # Check extension
            for ext in allow_extensions:
                if link.lower().endswith(ext.lower()):
                    filtered_links.append(link)
                    break

        # Check file existence
        existing_files = []
        missing_files = []

        # Get the Markdown file's directory for relative paths
        import os
        md_dir = os.path.dirname(md_path)

        for link in filtered_links:
            # URL-decode the path (e.g. %20 -> space)
            link_decoded = unquote(link)

            # Normalize the path
            if link_decoded.startswith('./'):
                link_decoded = link_decoded[2:]

            # Build full path relative to the Markdown file
            full_path = os.path.normpath(os.path.join(md_dir, link_decoded))

            if self._reader.file_exists(full_path):
                existing_files.append(link_decoded)
            else:
                missing_files.append(link_decoded)
        
        passed = len(missing_files) == 0
        details = []
        if existing_files:
            details.append(f"✅ Found: {len(existing_files)} files")
        if missing_files:
            details.append(f"❌ Not found: {', '.join(missing_files[:5])}")
        
        return passed, "\n".join(details)
    
    def check_markdown_section_item_count(self, path: str, heading: str, 
                                          min_items: int, item_kinds: List[str]) -> Tuple[bool, str]:
        """Checks the number of items in a Markdown section."""
        if not self._reader.file_exists(path):
            return False, f"File {path} not found"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"File {path} is empty"
        
        # Find the section
        heading_pattern = rf'^(#{{1,6}})\s*{re.escape(heading)}[.!?]?\s*$'
        match = re.search(heading_pattern, content, re.MULTILINE | re.IGNORECASE)

        if not match:
            return False, f"Section '{heading}' not found"

        # Get section content
        start_pos = match.end()
        next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)

        if next_heading:
            section_content = content[start_pos:start_pos + next_heading.start()]
        else:
            section_content = content[start_pos:]

        # Count items
        item_count = 0
        
        if "bullet" in item_kinds:
            # Count bullet lists (- or *)
            bullets = re.findall(r'^[\s]*[-*]\s+.+$', section_content, re.MULTILINE)
            item_count += len(bullets)
        
        if "numbered" in item_kinds:
            # Count numbered lists
            numbered = re.findall(r'^[\s]*\d+\.\s+.+$', section_content, re.MULTILINE)
            item_count += len(numbered)
        
        if "nonempty_line" in item_kinds and item_count == 0:
            # Count non-empty lines (if no lists were found)
            lines = [line for line in section_content.split('\n') if line.strip()]
            item_count = len(lines)
        
        passed = item_count >= min_items
        details = f"Found items: {item_count}, required: {min_items}"
        
        return passed, details
    
    def check_urls_in_markdown_section_min(self, path: str, heading: str, min_count: int) -> Tuple[bool, str]:
        """Checks the minimum number of URLs in a Markdown section."""
        if not self._reader.file_exists(path):
            return False, f"File {path} not found"
        
        content = self._reader.read_file(path)
        if not content:
            return False, f"File {path} is empty"
        
        # Find the section
        heading_pattern = rf'^(#{{1,6}})\s*{re.escape(heading)}[.!?]?\s*$'
        match = re.search(heading_pattern, content, re.MULTILINE | re.IGNORECASE)

        if not match:
            return False, f"Section '{heading}' not found"

        # Get section content
        start_pos = match.end()
        next_heading = re.search(r'^#{1,6}\s+', content[start_pos:], re.MULTILINE)

        if next_heading:
            section_content = content[start_pos:start_pos + next_heading.start()]
        else:
            section_content = content[start_pos:]

        # Find URLs
        url_pattern = r'https?://[^\s<>\[\]()\'\"]+[^\s<>\[\]()\'\".,;:!?]'
        urls = re.findall(url_pattern, section_content, re.IGNORECASE)
        
        # Filter out placeholders
        placeholder_patterns = [r'example\.com', r'your[-_]?link', r'placeholder']
        valid_urls = [url for url in urls if not any(re.search(p, url.lower()) for p in placeholder_patterns)]
        
        passed = len(valid_urls) >= min_count
        details = f"Found links: {len(valid_urls)}, required: {min_count}"
        
        return passed, details
    
    def check_pr_body_regex_count(self, base: str, merged: bool, pattern: str, min_prs: int) -> Tuple[bool, str]:
        """Checks the number of PRs with a pattern in their body."""
        prs = self._get_prs()
        
        # Filter PRs by base branch and status
        filtered_prs = []
        for pr in prs:
            if merged and not pr.get('merged_at'):
                continue
            if pr.get('base', {}).get('ref') != base:
                continue
            filtered_prs.append(pr)
        
        # Check PR body for the pattern
        matching_prs = 0
        for pr in filtered_prs:
            body = pr.get('body', '') or ''
            if re.search(pattern, body, re.IGNORECASE):
                matching_prs += 1
        
        passed = matching_prs >= min_prs
        details = f"PRs matching pattern: {matching_prs}, required: {min_prs}"
        
        return passed, details
    
    def check_pr_review_approvals(self, base: str, min_total_approvals: int) -> Tuple[bool, str]:
        """Checks the number of approvals in PR reviews."""
        prs = self._get_prs()
        
        total_approvals = 0
        for pr in prs:
            if pr.get('base', {}).get('ref') != base:
                continue
            
            # Get reviews for the PR
            pr_number = pr.get('number')
            if pr_number:
                reviews = self._client.get_pr_reviews(pr_number) if hasattr(self._client, 'get_pr_reviews') else []
                for review in reviews:
                    if review.get('state') == 'APPROVED':
                        total_approvals += 1
        
        passed = total_approvals >= min_total_approvals
        details = f"Total approvals: {total_approvals}, required: {min_total_approvals}"
        
        return passed, details
    
    def check_pr_review_line_comments(self, base: str, min_total_line_comments: int) -> Tuple[bool, str]:
        """Checks the number of line comments in PR reviews."""
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
        details = f"Total line comments: {total_comments}, required: {min_total_line_comments}"
        
        return passed, details
    
    def check_issue_exists(self, title_regex: str, state: str = "all") -> Tuple[bool, str]:
        """Checks the existence of an issue with the given pattern."""
        issues = self._get_issues()
        
        for issue in issues:
            if state != "all" and issue.get('state') != state:
                continue
            if re.search(title_regex, issue.get('title', ''), re.IGNORECASE):
                return True, f"Found issue: {issue.get('title')}"
        
        return False, f"Issue matching pattern '{title_regex}' not found"

    def check_commit_message_regex_count(self, pattern: str, min_count: int) -> Tuple[bool, str]:
        """Checks the number of commits matching the pattern."""
        commits = self._get_commits()
        
        matching_commits = 0
        for commit in commits:
            message = commit.get('commit', {}).get('message', '')
            if re.match(pattern, message):
                matching_commits += 1
        
        passed = matching_commits >= min_count
        details = f"Commits matching pattern: {matching_commits}, required: {min_count}"
        
        return passed, details

    def check_file_nonempty(self, path: str) -> bool:
        """Checks that the file exists and is not empty."""
        if not self._reader.file_exists(path):
            return False
        content = self._reader.read_file(path)
        return bool(content and content.strip())

    def check_issue_body_regex_all(self, title_regex: str, rules: Dict[str, Dict[str, str]]) -> Tuple[bool, str]:
        """Checks that the issue matching title_regex contains all specified regex patterns in its body."""
        issues = self._get_issues()
        matching_issue = None
        
        # Find issue by title_regex
        for issue in issues:
            if re.search(title_regex, issue.get('title', ''), re.IGNORECASE):
                matching_issue = issue
                break
        
        if not matching_issue:
            return False, f"Issue matching pattern '{title_regex}' not found"

        body = matching_issue.get('body', '') or ''
        missing_patterns = []
        
        # Check all rules
        for rule_name, rule_config in rules.items():
            pattern = rule_config.get('pattern', '')
            if pattern and not re.search(pattern, body, re.IGNORECASE):
                missing_patterns.append(f"{rule_name}: '{pattern}'")
        
        if missing_patterns:
            return False, f"Patterns not found in issue body: {', '.join(missing_patterns)}"
        
        return True, "All patterns found in issue body"

    def check_issue_comment_regex(self, title_regex: str, comment_pattern: str, state: str = "closed") -> Tuple[bool, str]:
        """Checks that an issue has a comment matching a regex pattern."""
        issues = self._get_issues()

        for issue in issues:
            if state != "all" and issue.get('state') != state:
                continue
            if not re.search(title_regex, issue.get('title', ''), re.IGNORECASE):
                continue

            # Found the issue, now check comments
            issue_number = issue.get('number')
            comments = self._client.get_issue_comments(issue_number)

            for comment in comments:
                body = comment.get('body', '') or ''
                if re.search(comment_pattern, body, re.IGNORECASE | re.DOTALL):
                    return True, f"Found matching comment on issue #{issue_number}"

            return False, f"Issue #{issue_number} exists but no comment matches pattern '{comment_pattern}'"

        return False, f"Issue matching '{title_regex}' (state={state}) not found"

    def check_pr_merged_exists(self, title_regex: str = None, closes_issue: bool = False) -> Tuple[bool, str]:
        """Checks that a merged PR exists with the specified parameters."""
        prs = self._get_prs()
        matching_prs = []
        
        for pr in prs:
            # Check that PR is merged
            if not pr.get('merged_at'):
                continue
            
            # Check title_regex if specified
            if title_regex:
                if not re.search(title_regex, pr.get('title', ''), re.IGNORECASE):
                    continue
            
            # Check closes_issue if required
            if closes_issue:
                body = pr.get('body', '') or ''
                if not re.search(r'(?i)(closes|fixes|resolves)\s+#\d+', body):
                    continue
            
            matching_prs.append(pr)
        
        if matching_prs:
            pr_titles = [pr.get('title', 'N/A')[:50] for pr in matching_prs[:3]]
            return True, f"Found merged PR: {', '.join(pr_titles)}"
        
        # Check if student accidentally PRed to the upstream (parent) repo
        upstream_hint = ""
        try:
            repo_info = self._client.get_repo_info()
            parent = repo_info.get('parent', {}) if repo_info else {}
            if parent:
                parent_name = parent.get('full_name', '')
                student_name = self._client._owner
                # Check upstream for PRs from this student
                import requests as req
                headers = dict(self._client._headers) if hasattr(self._client, '_headers') else {}
                resp = req.get(
                    f"https://api.github.com/repos/{parent_name}/pulls?state=all&per_page=30",
                    headers=headers, timeout=10
                )
                if resp.status_code == 200:
                    upstream_prs = resp.json()
                    student_prs = [p for p in upstream_prs
                                   if p.get('user', {}).get('login', '').lower() == student_name.lower()]
                    if student_prs:
                        upstream_hint = (
                            f" NOTE: Found {len(student_prs)} PR(s) from you in the upstream repo "
                            f"({parent_name}). PRs must target YOUR fork's main branch, not the original repo."
                        )
        except Exception:
            pass

        criteria = []
        if title_regex:
            criteria.append(f"title_regex='{title_regex}'")
        if closes_issue:
            criteria.append("closes_issue=True")

        msg = f"Merged PR not found (criteria: {', '.join(criteria) if criteria else 'merged'})"
        if upstream_hint:
            msg += upstream_hint
        return False, msg

    def check_pr_touches_paths(self, title_regex: str = None, paths: List[str] = None, min_files: int = 1) -> Tuple[bool, str]:
        """Checks that the PR modifies files at the specified paths."""
        prs = self._get_prs()
        matching_pr = None
        
        # Find PR by title_regex if specified
        if title_regex:
            for pr in prs:
                if re.search(title_regex, pr.get('title', ''), re.IGNORECASE):
                    matching_pr = pr
                    break
        else:
            # Take the latest merged PR
            merged_prs = [pr for pr in prs if pr.get('merged_at')]
            if merged_prs:
                matching_pr = merged_prs[0]
        
        if not matching_pr:
            return False, "PR not found"
        
        pr_number = matching_pr.get('number')
        if not pr_number:
            return False, "Could not get PR number"
        
        # Get the list of changed files from the PR
        pr_files = []
        try:
            pr_files_data = self._client._get(f"pulls/{pr_number}/files")
            if pr_files_data:
                pr_files = [f.get('filename', '') for f in pr_files_data]
        except Exception as e:
            return False, f"Could not get file list from PR: {str(e)}"
        
        if not pr_files:
            return False, "PR has no changed files"
        
        # Check path matching
        matched_files = []
        for file_path in pr_files:
            for pattern in paths:
                if fnmatch.fnmatch(file_path, pattern) or file_path.startswith(pattern.rstrip('*').rstrip('/')):
                    matched_files.append(file_path)
                    break
        
        passed = len(matched_files) >= min_files
        details = f"Files matched by paths: {len(matched_files)}/{min_files}"
        if matched_files:
            details += f" ({', '.join(matched_files[:5])})"
        
        return passed, details

    @staticmethod
    def _is_internal_ip(url: str) -> bool:
        """Returns True if the URL targets a private network IP."""
        m = re.search(r'//(\d+)\.(\d+)\.\d+\.\d+', url)
        if not m:
            return False
        a, b = int(m.group(1)), int(m.group(2))
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)

    def _http_check_via_relay(self, url: str, expect_status: int,
                              expect_body_regex: str, timeout: int) -> Tuple[bool, str]:
        """Route HTTP check through the relay worker for internal IPs.

        Retries up to 3 times on transient failures (worker timeout / not
        connected) to handle WebSocket reconnection after idle periods.
        """
        import os
        import time
        import requests

        relay_url = os.environ.get('RELAY_URL', 'http://dashboard:8000/relay/check')
        relay_token = os.environ.get('RELAY_TOKEN', '')

        max_attempts = 3
        last_error = ""
        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    relay_url,
                    json={"url": url, "timeout": timeout},
                    headers={"Authorization": f"Bearer {relay_token}"},
                    timeout=timeout + 20,
                )
                if resp.status_code in (503, 504) and attempt < max_attempts - 1:
                    last_error = resp.text
                    time.sleep(8)  # wait for worker to reconnect
                    continue
                if resp.status_code == 503:
                    return False, "Relay worker not connected (university VM offline)"
                if resp.status_code != 200:
                    return False, f"Relay error: {resp.text}"

                data = resp.json()
                if data.get("error"):
                    if attempt < max_attempts - 1:
                        last_error = data["error"]
                        time.sleep(8)
                        continue
                    return False, f"Relay check failed: {data['error']}"

                status_code = data.get("status_code", 0)
                body = data.get("body", "")

                if status_code != expect_status:
                    return False, f"Expected status {expect_status}, got {status_code}"

                if expect_body_regex:
                    if not re.search(expect_body_regex, body, re.IGNORECASE):
                        return False, f"Response body does not match pattern '{expect_body_regex}'"

                return True, f"Endpoint accessible (via relay), status {status_code}"

            except requests.exceptions.Timeout:
                if attempt < max_attempts - 1:
                    last_error = f"Relay timeout checking {url}"
                    time.sleep(8)
                    continue
                return False, f"Relay timeout checking {url}"
            except Exception as e:
                return False, f"Relay error: {str(e)}"

        return False, f"Relay failed after retries: {last_error}"

    def check_http_check(self, base_url: str, path: str, expect_status: int = 200,
                        expect_body_regex: str = None, timeout: int = 10) -> Tuple[bool, str]:
        """Checks an HTTP endpoint. Routes internal IPs through the relay worker."""
        import os
        import requests

        # Build the full URL
        if base_url.endswith('/') and path.startswith('/'):
            url = base_url.rstrip('/') + path
        elif not base_url.endswith('/') and not path.startswith('/'):
            url = base_url + '/' + path
        else:
            url = base_url + path

        # Route internal IPs through relay if RELAY_TOKEN is configured
        if os.environ.get('RELAY_TOKEN') and self._is_internal_ip(url):
            return self._http_check_via_relay(url, expect_status, expect_body_regex, timeout)

        try:
            response = requests.get(url, timeout=timeout)

            # Check status
            if response.status_code != expect_status:
                return False, f"Expected status {expect_status}, got {response.status_code}"

            # Check body_regex if specified
            if expect_body_regex:
                body = response.text
                if not re.search(expect_body_regex, body, re.IGNORECASE):
                    return False, f"Response body does not match pattern '{expect_body_regex}'"

            return True, f"Endpoint accessible, status {response.status_code}"

        except requests.exceptions.Timeout:
            return False, f"Timeout requesting {url}"
        except requests.exceptions.ConnectionError:
            return False, f"Connection error to {url}"
        except Exception as e:
            return False, f"Request error: {str(e)}"

    def check_api_access(self, required_endpoints: List[str]) -> Tuple[bool, str]:
        """Check that a student has called all required API endpoints.

        Queries the dashboard's /api/access-log/{github_alias} endpoint.
        """
        import os
        import requests

        github_alias = self._client._owner  # student's github username
        dashboard_url = os.environ.get("DASHBOARD_URL", "https://auche.namaz.live")
        relay_token = os.environ.get("RELAY_TOKEN", "")

        if not relay_token:
            return False, "RELAY_TOKEN not configured — cannot query API access log"

        try:
            resp = requests.get(
                f"{dashboard_url}/api/access-log/{github_alias}",
                headers={"Authorization": f"Bearer {relay_token}"},
                timeout=10,
            )
            if resp.status_code == 404:
                return False, f"User '{github_alias}' not found in autochecker"
            if resp.status_code != 200:
                return False, f"Dashboard returned {resp.status_code}: {resp.text[:200]}"

            data = resp.json()
            called = {e["endpoint"] for e in data.get("endpoints", [])}
            missing = [ep for ep in required_endpoints if ep not in called]

            if missing:
                return False, f"Missing API calls: {', '.join(missing)}. Called: {', '.join(sorted(called)) or 'none'}"
            return True, f"All required endpoints called: {', '.join(required_endpoints)}"

        except requests.exceptions.ConnectionError:
            return False, f"Cannot connect to dashboard at {dashboard_url}"
        except Exception as e:
            return False, f"Error checking API access: {e}"

    def _ssh_check_via_relay(self, host: str, port: int, username: str,
                             command: str, timeout: int) -> Tuple[bool, dict]:
        """Route SSH check through the relay worker for internal IPs.

        Retries up to 3 times on transient failures.
        Returns (success, result_dict) where result_dict has
        {exit_code, stdout, stderr, error}.
        """
        import os
        import time
        import requests

        relay_url = os.environ.get('RELAY_URL', 'http://dashboard:8000/relay/ssh')
        # Derive SSH relay URL from HTTP relay URL if needed
        if '/relay/check' in relay_url:
            relay_url = relay_url.replace('/relay/check', '/relay/ssh')
        elif not relay_url.endswith('/relay/ssh'):
            relay_url = relay_url.rstrip('/').rsplit('/relay/', 1)[0] + '/relay/ssh'

        relay_token = os.environ.get('RELAY_TOKEN', '')
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    relay_url,
                    json={"host": host, "port": port, "username": username,
                          "command": command, "timeout": timeout},
                    headers={"Authorization": f"Bearer {relay_token}"},
                    timeout=timeout + 20,
                )
                if resp.status_code in (503, 504) and attempt < max_attempts - 1:
                    time.sleep(8)
                    continue
                if resp.status_code == 503:
                    return False, {"exit_code": -1, "stdout": "", "stderr": "",
                                   "error": "Relay worker not connected (university VM offline)"}
                if resp.status_code != 200:
                    return False, {"exit_code": -1, "stdout": "", "stderr": "",
                                   "error": f"Relay error: {resp.text}"}

                data = resp.json()
                if data.get("error"):
                    if attempt < max_attempts - 1:
                        time.sleep(8)
                        continue
                    return False, data

                return True, data

            except requests.exceptions.Timeout:
                if attempt < max_attempts - 1:
                    time.sleep(8)
                    continue
                return False, {"exit_code": -1, "stdout": "", "stderr": "",
                               "error": f"Relay timeout for SSH to {host}"}
            except Exception as e:
                return False, {"exit_code": -1, "stdout": "", "stderr": "",
                               "error": f"Relay error: {str(e)}"}

        return False, {"exit_code": -1, "stdout": "", "stderr": "",
                       "error": "Relay failed after retries"}

    def check_ssh(self, host: str, username: str, command: str,
                  expect_regex: str = None, expect_exit: int = 0,
                  port: int = 22, timeout: int = 10) -> Tuple[bool, str]:
        """SSH into a host, run a command, and validate output.

        Args:
            expect_exit: Expected exit code. Use -1 for "any non-zero".
        """
        import os
        import subprocess

        is_internal = re.match(r'^(10\.\d|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)', host)

        if is_internal and os.environ.get('RELAY_TOKEN'):
            success, data = self._ssh_check_via_relay(host, port, username, command, timeout)
            if not success:
                return False, data.get("error", "SSH relay failed")
        else:
            key_path = os.environ.get('SSH_KEY_PATH', '/app/ssh_key')
            if not os.path.exists(key_path):
                return False, f"SSH key not found at {key_path}"

            try:
                result = subprocess.run(
                    ["ssh", "-i", key_path,
                     "-o", "StrictHostKeyChecking=no",
                     "-o", "UserKnownHostsFile=/dev/null",
                     "-o", f"ConnectTimeout={timeout}",
                     "-o", "LogLevel=ERROR",
                     "-p", str(port),
                     f"{username}@{host}", command],
                    capture_output=True, text=True, timeout=timeout + 5,
                )
                data = {
                    "exit_code": result.returncode,
                    "stdout": result.stdout[:4096],
                    "stderr": result.stderr[:4096],
                    "error": "",
                }
            except subprocess.TimeoutExpired:
                return False, f"SSH connection timed out after {timeout}s"
            except Exception as e:
                return False, f"SSH error: {str(e)}"

        exit_code = data.get("exit_code", -1)
        stdout = data.get("stdout", "").strip()

        # Validate exit code
        if expect_exit == -1:
            # Expect any non-zero
            if exit_code == 0:
                return False, f"Expected non-zero exit code, got 0. Output: {stdout[:200]}"
        elif exit_code != expect_exit:
            return False, f"Expected exit code {expect_exit}, got {exit_code}. Output: {stdout[:200]}"

        # Validate output regex
        if expect_regex:
            if not re.search(expect_regex, stdout):
                return False, f"Output does not match '{expect_regex}'. Got: {stdout[:200]}"

        return True, f"SSH check passed (exit={exit_code}, output={stdout[:100]})"

    def check_clone_and_run(self, commands: List[str], timeout: int = 120) -> Tuple[bool, str]:
        """Clones the repo and runs commands in a sandboxed Docker container.

        Uses a shallow clone into a shared host directory, then executes
        commands inside an ephemeral container with strict resource limits
        and no access to the bot's environment.
        """
        import subprocess
        import tempfile
        import shutil
        import os

        owner = self._client._owner
        repo = self._client._repo_name
        clone_url = f"https://github.com/{owner}/{repo}.git"
        branch = self._branch or "main"

        sandbox_dir = os.environ.get("SANDBOX_DIR", "/tmp/autochecker-sandbox")
        os.makedirs(sandbox_dir, exist_ok=True)
        tmpdir = tempfile.mkdtemp(prefix="run_", dir=sandbox_dir)

        try:
            # Shallow clone (runs on host / bot container)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, clone_url, tmpdir],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return False, f"git clone failed: {result.stderr.strip()}"

            # Check if Docker is available for sandboxed execution
            docker_available = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            ).returncode == 0

            if docker_available:
                return self._run_in_sandbox(tmpdir, commands, timeout)
            else:
                # Fallback to direct execution (e.g. local dev without Docker)
                return self._run_direct(tmpdir, commands, timeout)

        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            return False, f"Clone/run error: {str(e)}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _run_in_sandbox(self, workdir: str, commands: List[str], timeout: int) -> Tuple[bool, str]:
        """Run commands inside a sandboxed Docker container."""
        import subprocess

        cmd_chain = " && ".join(commands)
        docker_cmd = [
            "docker", "run", "--rm",
            "--memory=512m",
            "--cpus=1",
            "--pids-limit=256",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "-v", f"{workdir}:{workdir}",
            "-w", workdir,
            "autochecker-sandbox:latest",
            "sh", "-c", cmd_chain,
        ]

        result = subprocess.run(
            docker_cmd, capture_output=True, text=True, timeout=timeout
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            output = stderr or stdout
            if len(output) > 500:
                output = output[:500] + "..."
            return False, f"Command failed (exit {result.returncode}): {output}"

        return True, "All commands passed (sandboxed)"

    def _run_direct(self, workdir: str, commands: List[str], timeout: int) -> Tuple[bool, str]:
        """Fallback: run commands directly (for local dev without Docker)."""
        import subprocess
        import os

        # Sanitise environment: drop vars that leak from the host and
        # confuse uv / venv discovery inside the cloned project.
        env = {k: v for k, v in os.environ.items()
               if k not in ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")}

        for cmd in commands:
            result = subprocess.run(
                cmd, shell=True, cwd=workdir,
                capture_output=True, text=True, timeout=timeout,
                env=env,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                output = stderr or stdout
                if len(output) > 500:
                    output = output[:500] + "..."
                return False, f"Command `{cmd}` failed (exit {result.returncode}): {output}"

        return True, "All commands passed"

    def _find_pr_for_issue(self, title_regex: str) -> Tuple[Optional[Dict], str]:
        """Finds the PR that closes a specific issue (by issue title regex).

        1. Find issue by title_regex → get issue number
        2. Search all PRs for Closes/Fixes/Resolves #N in body
        3. Return (pr_dict or None, details_string)
        """
        issues = self._get_issues()
        issue = None
        for i in issues:
            if re.search(title_regex, i.get('title', ''), re.IGNORECASE):
                issue = i
                break

        if not issue:
            return None, f"Issue with pattern '{title_regex}' not found"

        issue_number = issue.get('number')
        if not issue_number:
            return None, "Issue has no number"

        prs = self._get_prs()
        close_pattern = rf'(?i)(closes|fixes|resolves)\s+#({issue_number})\b'

        for pr in prs:
            body = pr.get('body', '') or ''
            if re.search(close_pattern, body):
                return pr, f"Found PR #{pr.get('number')}: {pr.get('title', '')}"

        return None, f"No PR found that closes issue #{issue_number}"

    def check_issue_has_linked_pr(self, title_regex: str, merged: bool = True) -> Tuple[bool, str]:
        """Checks that there is a PR closing the issue found by title_regex."""
        pr, details = self._find_pr_for_issue(title_regex)
        if not pr:
            return False, details

        if merged and not pr.get('merged_at'):
            return False, f"PR #{pr.get('number')} exists but is not merged"

        return True, details

    def check_issue_pr_approved(self, title_regex: str, min_approvals: int = 1) -> Tuple[bool, str]:
        """Checks that the PR closing the issue has enough approvals."""
        pr, details = self._find_pr_for_issue(title_regex)
        if not pr:
            return False, details

        pr_number = pr.get('number')
        reviews = self._client.get_pr_reviews(pr_number) if hasattr(self._client, 'get_pr_reviews') else []
        approvals = sum(1 for r in reviews if r.get('state') == 'APPROVED')

        if approvals >= min_approvals:
            return True, f"PR #{pr_number} has {approvals} approval(s)"
        return False, f"PR #{pr_number} has {approvals} approval(s), needs {min_approvals}"

    def check_issue_pr_review_comments(self, title_regex: str, min_comments: int = 1) -> Tuple[bool, str]:
        """Checks that the PR closing the issue has enough line-level review comments."""
        pr, details = self._find_pr_for_issue(title_regex)
        if not pr:
            return False, details

        pr_number = pr.get('number')
        comments = self._client.get_pr_review_comments(pr_number) if hasattr(self._client, 'get_pr_review_comments') else []
        count = len(comments)

        if count >= min_comments:
            return True, f"PR #{pr_number} has {count} review comment(s)"
        return False, f"PR #{pr_number} has {count} review comment(s), needs {min_comments}"

    def run_check(self, check_id: str, check_type: str, params: Dict[str, Any], description: str = "", hint: str = "") -> CheckResult:
        """Runs a single check by its type."""
        status = "FAIL"
        details = ""
        try:
            if check_type == "repo_exists":
                if self.check_repo_exists(): status = "PASS"

            elif check_type == "repo_is_fork":
                if self.check_repo_is_fork(): status = "PASS"

            elif check_type == "repo_has_issues":
                if self.check_repo_has_issues(): status = "PASS"
            
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
            
            elif check_type == "issue_has_linked_pr":
                title_regex = params.get('title_regex', '')
                merged = params.get('merged', True)
                passed, details = self.check_issue_has_linked_pr(title_regex, merged)
                if passed: status = "PASS"

            elif check_type == "issue_pr_approved":
                title_regex = params.get('title_regex', '')
                min_approvals = params.get('min_approvals', 1)
                passed, details = self.check_issue_pr_approved(title_regex, min_approvals)
                if passed: status = "PASS"

            elif check_type == "issue_pr_review_comments":
                title_regex = params.get('title_regex', '')
                min_comments = params.get('min_comments', 1)
                passed, details = self.check_issue_pr_review_comments(title_regex, min_comments)
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
            
            elif check_type == "file_nonempty":
                path = params.get('path', '')
                if self.check_file_nonempty(path): 
                    status = "PASS"
                else:
                    details = f"File {path} is empty or does not exist"
            
            elif check_type == "issue_body_regex_all":
                title_regex = params.get('title_regex', '')
                rules = params.get('rules', {})
                passed, details = self.check_issue_body_regex_all(title_regex, rules)
                if passed: status = "PASS"

            elif check_type == "issue_comment_regex":
                title_regex = params.get('title_regex', '')
                comment_pattern = params.get('comment_pattern', '')
                state = params.get('state', 'closed')
                passed, details = self.check_issue_comment_regex(title_regex, comment_pattern, state)
                if passed: status = "PASS"

            elif check_type == "pr_merged_exists":
                title_regex = params.get('title_regex')
                closes_issue = params.get('closes_issue', False)
                passed, details = self.check_pr_merged_exists(title_regex, closes_issue)
                if passed: status = "PASS"
            
            elif check_type == "pr_touches_paths":
                title_regex = params.get('title_regex')
                paths = params.get('paths', [])
                min_files = params.get('min_files', 1)
                passed, details = self.check_pr_touches_paths(title_regex, paths, min_files)
                if passed: status = "PASS"
            
            elif check_type == "http_check":
                # Get base_url from runtime.prod or params
                runtime = params.get('runtime', 'prod')
                base_url_template = params.get('base_url')
                
                # If base_url is not specified directly, try to get it from lab_spec
                if not base_url_template and self._lab_spec:
                    rt = getattr(self._lab_spec, 'runtime', None)
                    if isinstance(rt, dict):
                        runtime_config = rt.get(runtime)
                    elif rt is not None:
                        runtime_config = getattr(rt, runtime, None)
                    else:
                        runtime_config = None
                    if runtime_config:
                        if isinstance(runtime_config, dict):
                            base_url_template = runtime_config.get('base_url')
                        else:
                            base_url_template = getattr(runtime_config, 'base_url', None)
                
                # If still not found, use environment variable or default
                if not base_url_template:
                    import os
                    server_ip = os.environ.get('SERVER_IP', 'localhost')
                    base_url_template = f"http://{server_ip}"
                
                # Replace {server_ip} if present
                if '{server_ip}' in base_url_template:
                    import os
                    server_ip = os.environ.get('SERVER_IP', 'localhost')
                    base_url = base_url_template.replace('{server_ip}', server_ip)
                else:
                    base_url = base_url_template
                
                path = params.get('path', '/')
                expect_status = params.get('expect_status', 200)
                expect_body_regex = params.get('expect_body_regex')
                timeout = params.get('timeout', 10)
                
                passed, details = self.check_http_check(base_url, path, expect_status, expect_body_regex, timeout)
                if passed: status = "PASS"
            
            elif check_type == "ssh_check":
                import os
                # Resolve server_ip (same mechanism as http_check)
                runtime = params.get('runtime', 'prod')
                base_url_template = None
                if self._lab_spec:
                    rt = getattr(self._lab_spec, 'runtime', None)
                    if isinstance(rt, dict):
                        runtime_config = rt.get(runtime)
                    elif rt is not None:
                        runtime_config = getattr(rt, runtime, None)
                    else:
                        runtime_config = None
                    if runtime_config:
                        if isinstance(runtime_config, dict):
                            base_url_template = runtime_config.get('base_url')
                        else:
                            base_url_template = getattr(runtime_config, 'base_url', None)

                ssh_host = os.environ.get('SERVER_IP', 'localhost')
                if base_url_template and '{server_ip}' in base_url_template:
                    pass  # ssh_host already set from SERVER_IP env

                command = params.get('command', 'echo ok')
                expect_regex = params.get('expect_regex')
                expect_exit = params.get('expect_exit', 0)
                username = params.get('username', 'autochecker')
                port = params.get('port', 22)
                timeout = params.get('timeout', 10)

                passed, details = self.check_ssh(ssh_host, username, command,
                                                  expect_regex, expect_exit, port, timeout)
                if passed: status = "PASS"

            elif check_type == "clone_and_run":
                commands = params.get('commands', [])
                timeout = params.get('timeout', 120)
                passed, details = self.check_clone_and_run(commands, timeout)
                if passed: status = "PASS"

            elif check_type == "any_of":
                # Composite check: passes if ANY child check passes.
                child_checks = params.get('checks', [])
                if not child_checks:
                    status = "ERROR"
                    details = "any_of: no child checks defined"
                else:
                    child_results = []
                    for i, child in enumerate(child_checks):
                        child_type = child.get('type', '')
                        child_params = child.get('params', {})
                        child_id = f"{check_id}[{i}]"
                        result = self.run_check(child_id, child_type, child_params)
                        child_results.append(result)
                        if result.get('status') == 'PASS':
                            status = "PASS"
                            details = f"Matched alternative {i + 1}/{len(child_checks)}: {result.get('details', '')}"
                            break
                    if status != "PASS":
                        fail_details = "; ".join(
                            f"alt {i + 1}: {r.get('details', 'FAIL')}"
                            for i, r in enumerate(child_results)
                        )
                        details = f"No alternative passed ({fail_details})"

            elif check_type == "api_access_check":
                required_endpoints = params.get('endpoints', [])
                passed, details = self.check_api_access(required_endpoints)
                if passed: status = "PASS"

            elif check_type == "llm_judge":
                # LLM checks are handled separately, not through engine
                status = "SKIP"
                details = "LLM check is handled separately"

            else:
                # Unsupported check types
                status = "ERROR"
                unsupported_checks = {
                    "branch_protection_enabled": "Branch protection check is not implemented. Requires access to GitHub API for Branch Rulesets.",
                    "file_min_bytes": "Minimum file size check is not implemented.",
                    "pr_links_issue": "PR-to-issue link check is not implemented.",
                }
                details = unsupported_checks.get(
                    check_type,
                    f"Check type '{check_type}' is not implemented. Please add implementation in engine.py"
                )

        except Exception as e:
            status = "ERROR"
            details = f"Error executing check '{check_id}': {e}"
        
        return CheckResult(id=check_id, status=status, details=details, description=description, hint=hint)
