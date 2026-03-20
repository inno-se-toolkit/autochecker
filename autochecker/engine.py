# autochecker/engine.py
import random
import re
import fnmatch
from typing import List, Dict, Any, Optional, Tuple
from .github_client import GitHubClient
from .repo_reader import RepoReader


def _sample_eval_questions(questions: list, sample_per_class: int) -> list:
    """Sample N questions per class from the eval pool.

    Classes are derived from the question index:
      A (0,1,10,11)  B (2,3,12,13)  C (4,5,14,15)  D (6,7,16,17)  E (8,9,18,19)

    Within each class, hidden (bot_only) questions are preferred.
    """
    def _class_of(idx: int) -> str:
        return chr(ord("A") + (idx % 10) // 2)

    by_class: dict[str, list] = {}
    for q in questions:
        cls = _class_of(q["index"])
        by_class.setdefault(cls, []).append(q)

    sampled = []
    for cls in sorted(by_class):
        pool = by_class[cls]
        # prefer hidden questions
        hidden = [q for q in pool if q.get("bot_only")]
        local = [q for q in pool if not q.get("bot_only")]
        ordered = hidden + local
        sampled.extend(ordered[:sample_per_class])

    sampled.sort(key=lambda q: q["index"])
    return sampled

class CheckResult(Dict):
    id: str
    status: str # PASS, FAIL, ERROR
    description: str
    details: Optional[str]
    hint: Optional[str]

class CheckEngine:
    """Engine that runs data-based checks."""
    def __init__(self, client: GitHubClient, reader: RepoReader, branch: Optional[str] = None, lab_spec: Optional[Any] = None,
                 server_ip: Optional[str] = None, lms_api_key: Optional[str] = None,
                 vm_username: Optional[str] = None):
        self._client = client
        self._reader = reader
        self._branch = branch
        self._server_ip = server_ip
        self._lms_api_key = lms_api_key
        self._vm_username = vm_username
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

    def check_commit_message_regex(self, pattern: str) -> Tuple[bool, str]:
        commits = self._get_commits()
        if not commits:
            return False, "No commits found in the repository."
        # Check that ANY commit matches the pattern
        for commit in commits:
            if re.search(pattern, commit['commit']['message']):
                msg = commit['commit']['message'].split('\n')[0]
                return True, f"Found matching commit: \"{msg}\""
        recent = [c['commit']['message'].split('\n')[0] for c in commits[:5]]
        recent_list = "; ".join(f'"{m}"' for m in recent)
        return False, (
            f"No commit message matches pattern: {pattern}. "
            f"Recent commits: {recent_list}. "
            f"Make sure your commit message follows the required format."
        )

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
    
    def check_glob_exists(self, patterns: List[str], min_matches: int = 0) -> Tuple[bool, str]:
        """Checks file existence by glob patterns.

        If min_matches > 0, passes when at least that many patterns match.
        If min_matches == 0 (default), ALL patterns must match.
        """
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

        if min_matches > 0:
            passed = len(matched_patterns) >= min_matches
        else:
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

        state_info = f" (state: {state})" if state != "all" else ""
        issue_count = len(issues)
        return False, (
            f"No issue found matching title pattern: {title_regex}{state_info}. "
            f"Searched {issue_count} issue(s). "
            f"Create a GitHub issue with the correct title."
        )

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

    def _http_check_via_relay(self, url: str, expect_status,
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

                allowed = expect_status if isinstance(expect_status, list) else [expect_status]
                if status_code not in allowed:
                    body_preview = body[:200].strip() if body else "(empty body)"
                    return False, (
                        f"GET {url} → {status_code} (expected {allowed}). "
                        f"Response: {body_preview}"
                    )

                if expect_body_regex:
                    if not re.search(expect_body_regex, body, re.IGNORECASE):
                        body_preview = body[:200].strip() if body else "(empty body)"
                        return False, (
                            f"GET {url} → {status_code} but response body "
                            f"does not match pattern '{expect_body_regex}'. "
                            f"Body preview: {body_preview}"
                        )

                return True, f"GET {url} → {status_code} (via relay)"

            except requests.exceptions.Timeout:
                if attempt < max_attempts - 1:
                    last_error = f"Relay timeout checking {url}"
                    time.sleep(8)
                    continue
                return False, f"Relay timeout checking {url}"
            except Exception as e:
                return False, f"Relay error: {str(e)}"

        return False, f"Relay failed after retries: {last_error}"

    def check_http_check(self, base_url: str, path: str, expect_status = 200,
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
            allowed = expect_status if isinstance(expect_status, list) else [expect_status]
            if response.status_code not in allowed:
                body_preview = response.text[:200].strip() if response.text else "(empty body)"
                return False, (
                    f"GET {url} → {response.status_code} (expected {allowed}). "
                    f"Response: {body_preview}"
                )

            # Check body_regex if specified
            if expect_body_regex:
                body = response.text
                if not re.search(expect_body_regex, body, re.IGNORECASE):
                    body_preview = body[:200].strip() if body else "(empty body)"
                    return False, (
                        f"GET {url} → {response.status_code} but response body "
                        f"does not match pattern '{expect_body_regex}'. "
                        f"Body preview: {body_preview}"
                    )

            return True, f"GET {url} → {response.status_code}"

        except requests.exceptions.Timeout:
            return False, (
                f"GET {url} timed out after {timeout}s. "
                f"Check that your VM is running and the port is open."
            )
        except requests.exceptions.ConnectionError as e:
            err = str(e)
            if "Name or service not known" in err or "getaddrinfo" in err:
                hint = "DNS resolution failed — check the hostname/IP."
            elif "Connection refused" in err:
                hint = "Connection refused — is the service running and listening on the right port?"
            elif "Network is unreachable" in err:
                hint = "Network unreachable — check your VM's network configuration."
            else:
                hint = f"Details: {err[:200]}"
            return False, f"Connection error to {url}. {hint}"
        except Exception as e:
            return False, f"GET {url} failed: {str(e)[:200]}"

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

    def _direct_ssh(self, host: str, port: int, username: str,
                     command: str, timeout: int) -> Tuple[bool, dict]:
        """Run SSH command directly from the bot container (for public IPs)."""
        import subprocess

        ssh_key = "/app/ssh_key"
        try:
            result = subprocess.run(
                ["ssh", "-i", ssh_key,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "UserKnownHostsFile=/dev/null",
                 "-o", f"ConnectTimeout={min(timeout, 10)}",
                 "-o", "LogLevel=ERROR",
                 "-p", str(port),
                 f"{username}@{host}", command],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            return True, {
                "exit_code": result.returncode,
                "stdout": result.stdout[:65536],
                "stderr": result.stderr[:4096],
                "error": "",
            }
        except subprocess.TimeoutExpired:
            return False, {"exit_code": -1, "stdout": "", "stderr": "", "error": "timeout"}
        except Exception as e:
            return False, {"exit_code": -1, "stdout": "", "stderr": "", "error": str(e)}

    def _ssh_check_via_relay(self, host: str, port: int, username: str,
                             command: str, timeout: int) -> Tuple[bool, dict]:
        """Route SSH check through the relay worker for internal IPs.

        For public IPs, uses direct SSH from the bot container instead.
        Retries up to 3 times on transient failures.
        Returns (success, result_dict) where result_dict has
        {exit_code, stdout, stderr, error}.
        """
        import os
        import time
        import requests

        # Public IPs: use direct SSH, skip the relay
        if not host.startswith("10."):
            return self._direct_ssh(host, port, username, command, timeout)

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
                return False, (
                    f"SSH {username}@{host} timed out after {timeout}s. "
                    f"Check that the VM is running and port {port} is open."
                )
            except Exception as e:
                return False, f"SSH {username}@{host} failed: {str(e)[:200]}"

        exit_code = data.get("exit_code", -1)
        stdout = data.get("stdout", "").strip()

        # Validate exit code
        if expect_exit == -1:
            # Expect any non-zero
            if exit_code == 0:
                return False, (
                    f"SSH {username}@{host}: expected non-zero exit code, got 0. "
                    f"Output: {stdout[:200]}"
                )
        elif exit_code != expect_exit:
            stderr = data.get("stderr", "").strip()
            output_info = stderr[:200] if stderr else stdout[:200]
            return False, (
                f"SSH {username}@{host}: command exited with {exit_code} "
                f"(expected {expect_exit}). Output: {output_info}"
            )

        # Validate output regex
        if expect_regex:
            if not re.search(expect_regex, stdout):
                return False, (
                    f"SSH {username}@{host}: output does not match "
                    f"expected pattern '{expect_regex}'. Got: {stdout[:200]}"
                )

        return True, f"SSH {username}@{host} → OK (exit={exit_code})"

    def _ssh_exec_raw(self, host: str, username: str, command: str,
                      port: int = 22, timeout: int = 60) -> Tuple[bool, dict]:
        """Execute a command via SSH and return raw output.

        Returns (success, data) where data has {exit_code, stdout, stderr, error}.
        Uses relay for internal IPs when RELAY_TOKEN is set.
        """
        import os
        import subprocess

        is_internal = re.match(r'^(10\.\d|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)', host)

        if is_internal and os.environ.get('RELAY_TOKEN'):
            return self._ssh_check_via_relay(host, port, username, command, timeout)

        key_path = os.environ.get('SSH_KEY_PATH', '/app/ssh_key')
        if not os.path.exists(key_path):
            return False, {"exit_code": -1, "stdout": "", "stderr": "",
                           "error": f"SSH key not found at {key_path}"}

        try:
            result = subprocess.run(
                ["ssh", "-i", key_path,
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "UserKnownHostsFile=/dev/null",
                 "-o", f"ConnectTimeout={min(timeout, 10)}",
                 "-o", "LogLevel=ERROR",
                 "-p", str(port),
                 f"{username}@{host}", command],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            return True, {
                "exit_code": result.returncode,
                "stdout": result.stdout[:8192],
                "stderr": result.stderr[:4096],
                "error": "",
            }
        except subprocess.TimeoutExpired:
            return False, {"exit_code": -1, "stdout": "", "stderr": "",
                           "error": f"SSH {username}@{host} timed out after {timeout}s"}
        except Exception as e:
            return False, {"exit_code": -1, "stdout": "", "stderr": "",
                           "error": f"SSH {username}@{host} failed: {str(e)[:200]}"}

    def check_agent_eval_clone_and_run(
        self, eval_lab: str,
        include_bot_only: bool = True,
        bot_only_exclusively: bool = False,
        max_tier: int = 3,
        min_pass_rate: float = 0.75,
        timeout_per_question: int = 60,
        sample_per_class: int = 0,
    ) -> Tuple[bool, str]:
        """Run agent evaluation: clone repo, run agent.py in sandbox.

        For tier 2 questions (query_api), the student's backend must be
        deployed on their VM. A relay proxy bridges HTTP from Hetzner
        to the student VM through the relay worker.

        Agent.py runs in an isolated sandbox container with only:
        - The cloned repo (mounted volume)
        - LLM credentials (Groq)
        - Backend URL (relay proxy for VM, or direct for localhost)
        No access to /app/, Docker socket, specs, or other student data.
        """
        import json
        import os
        import shutil
        import subprocess
        import tempfile
        import threading
        import time
        import yaml

        # Load eval questions
        specs_dir = os.path.join(os.path.dirname(__file__), '..', 'specs')
        eval_file = os.path.join(specs_dir, f"{eval_lab}-eval.yaml")
        if not os.path.exists(eval_file):
            return False, f"Eval file not found: {eval_lab}-eval.yaml"

        with open(eval_file) as f:
            all_questions = yaml.safe_load(f) or []

        questions = []
        for q in all_questions:
            if bot_only_exclusively and not q.get("bot_only", False):
                continue
            elif not include_bot_only and q.get("bot_only", False):
                continue
            if q.get("tier", 1) > max_tier:
                continue
            questions.append(q)
        questions.sort(key=lambda q: q["index"])

        if sample_per_class > 0:
            questions = _sample_eval_questions(questions, sample_per_class)

        if not questions:
            return False, "No questions matched the filter criteria"

        # Clone student repo
        owner = self._client._owner
        repo = self._client._repo_name
        clone_url = f"https://github.com/{owner}/{repo}.git"
        branch = self._branch or "main"

        sandbox_dir = os.environ.get("SANDBOX_DIR", "/tmp/autochecker-sandbox")
        os.makedirs(sandbox_dir, exist_ok=True)
        tmpdir = tempfile.mkdtemp(prefix="eval_", dir=sandbox_dir)

        # Determine backend URL (student VM via relay proxy)
        server_ip = self._server_ip or os.environ.get("SERVER_IP", "localhost")
        backend_port = 42002
        vm_backend_url = f"http://{server_ip}:{backend_port}"
        use_relay = (
            os.environ.get("RELAY_TOKEN")
            and self._is_internal_ip(vm_backend_url)
        )

        # Get LMS_API_KEY from student VM via SSH relay
        lms_api_key = ""

        proxy_server = None
        proxy_port = None

        try:
            # 1. Shallow clone
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, clone_url, tmpdir],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                return False, f"git clone failed: {result.stderr.strip()[:200]}"

            # 2. Check if any tier 2 questions need the backend
            has_tier2 = any(q.get("tier", 1) >= 2 for q in questions)

            if has_tier2:
                # Verify backend is reachable
                if use_relay:
                    ok, detail = self._http_check_via_relay(
                        f"{vm_backend_url}/docs", [200, 401, 403], None, 15
                    )
                    if not ok:
                        return False, (
                            f"Student backend not reachable at {vm_backend_url}: {detail}. "
                            "Make sure Docker Compose is running on your VM."
                        )

                    # Get LMS_API_KEY from bot (student submits via Telegram)
                    lms_api_key = self._lms_api_key or os.environ.get("STUDENT_LMS_API_KEY", "")
                    if not lms_api_key:
                        lms_api_key = "my-secret-api-key"

                    # Start relay HTTP proxy so sandbox can reach student VM
                    proxy_port, proxy_server = self._start_relay_proxy(
                        server_ip, backend_port
                    )
                    backend_url = f"http://host.docker.internal:{proxy_port}"
                else:
                    # Direct access (localhost or public IP)
                    backend_url = vm_backend_url
                    # Try to read LMS_API_KEY from cloned .env.docker.secret
                    env_file = os.path.join(tmpdir, ".env.docker.secret")
                    if os.path.exists(env_file):
                        with open(env_file) as f:
                            for line in f:
                                if line.startswith("LMS_API_KEY="):
                                    lms_api_key = line.split("=", 1)[1].strip()
                                    break
            else:
                backend_url = "http://localhost:42002"  # unused, but set for agent

            # 3. Prepare LLM credentials
            llm_api_key = os.environ.get("LLM_API_KEY", "")
            llm_api_base = os.environ.get("LLM_API_URL", "")
            if llm_api_base.endswith("/chat/completions"):
                llm_api_base = llm_api_base[: -len("/chat/completions")]
            llm_model = os.environ.get("LLM_API_MODEL", "")

            # 4. Write .env.agent.secret so agents that require the file can find it
            env_secret_path = os.path.join(tmpdir, ".env.agent.secret")
            with open(env_secret_path, "w") as f:
                f.write(f"LLM_API_KEY={llm_api_key}\n")
                f.write(f"LLM_API_BASE_URL={llm_api_base}\n")
                f.write(f"LLM_API_BASE={llm_api_base}\n")
                f.write(f"LLM_API_MODEL={llm_model}\n")
                f.write(f"LLM_MODEL={llm_model}\n")

            # Write questions file and runner script into cloned repo
            questions_path = os.path.join(tmpdir, "_eval_questions.json")
            with open(questions_path, "w") as f:
                json.dump([{"index": q["index"], "question": q["question"]} for q in questions], f)

            runner_script = os.path.join(tmpdir, "_eval_runner.py")
            with open(runner_script, "w") as f:
                f.write('''\
import json, subprocess, sys, time

with open("_eval_questions.json") as f:
    questions = json.load(f)

results = {}
for qi, q in enumerate(questions):
    if qi > 0:
        time.sleep(1)
    idx = q["index"]
    escaped = q["question"].replace("'", "'\\\\''")
    cmd = f"uv run --python-preference only-system agent.py '{escaped}'"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
        results[str(idx)] = {"rc": r.returncode, "stdout": r.stdout.strip()[:65536], "stderr": r.stderr.strip()[-500:]}
    except subprocess.TimeoutExpired:
        results[str(idx)] = {"rc": -1, "stdout": "", "stderr": "timeout"}

with open("_eval_results.json", "w") as f:
    json.dump(results, f)
''')

            # 5. Run all questions in a single sandbox container
            env_flags = [
                "-e", f"LLM_API_KEY={llm_api_key}",
                "-e", f"LLM_API_BASE_URL={llm_api_base}",
                "-e", f"LLM_API_BASE={llm_api_base}",
                "-e", f"LLM_API_MODEL={llm_model}",
                "-e", f"LLM_MODEL={llm_model}",
                "-e", f"LMS_API_KEY={lms_api_key}",
                "-e", f"AGENT_API_BASE_URL={backend_url}",
            ]
            docker_cmd = [
                "docker", "run", "--rm",
                "--memory=512m",
                "--cpus=1",
                "--pids-limit=256",
                "--security-opt=no-new-privileges",
                "--add-host=host.docker.internal:host-gateway",
                "-v", f"{tmpdir}:{tmpdir}",
                "-w", tmpdir,
            ] + env_flags + [
                "autochecker-sandbox:latest",
                "sh", "-c",
                "uv sync --python-preference only-system --quiet 2>/dev/null; "
                "python _eval_runner.py",
            ]

            total_timeout = timeout_per_question * len(questions) + 120
            try:
                subprocess.run(
                    docker_cmd,
                    capture_output=True, text=True,
                    timeout=total_timeout,
                )
            except subprocess.TimeoutExpired:
                pass  # partial results may still be written

            # 6. Read results and evaluate
            results_path = os.path.join(tmpdir, "_eval_results.json")
            if os.path.exists(results_path):
                with open(results_path) as f:
                    agent_outputs = json.load(f)
            else:
                agent_outputs = {}

            passed_count = 0
            total = len(questions)
            results = []

            for q in questions:
                question_text = q["question"]
                expected = q.get("expected", {})
                idx = str(q["index"])

                ao = agent_outputs.get(idx)
                if not ao:
                    results.append(f"  x [{q['index']}] Agent did not produce results (container killed?)")
                    continue

                if ao["stderr"] == "timeout":
                    results.append(f"  x [{q['index']}] Agent timed out (90s)")
                    continue

                if ao["rc"] != 0:
                    stderr_preview = ao["stderr"][:100]
                    results.append(
                        f"  x [{q['index']}] Agent exited with code "
                        f"{ao['rc']}: {stderr_preview}"
                    )
                    continue

                stdout = ao["stdout"]
                if not stdout:
                    results.append(f"  x [{q['index']}] Agent produced no output")
                    continue

                try:
                    output = json.loads(stdout)
                except json.JSONDecodeError:
                    results.append(f"  x [{q['index']}] Invalid JSON: {stdout[:100]}")
                    continue

                answer = output.get("answer", "")
                if not answer:
                    results.append(f"  x [{q['index']}] Missing 'answer' field")
                    continue

                # Match answer — prefer LLM judge (rubric) when available
                rubric = q.get("rubric")
                if rubric:
                    answer_ok = self._llm_judge(answer, rubric)
                    if not answer_ok and expected:
                        answer_ok = self._match_answer(answer, expected)
                elif expected:
                    answer_ok = self._match_answer(answer, expected)
                else:
                    answer_ok = False

                # Check source
                source_ok = True
                expected_source = q.get("expected_source")
                if expected_source:
                    source = output.get("source", "")
                    if not source or not self._match_answer(source, expected_source):
                        source_ok = False

                # Check tools
                tools_ok = True
                check_tools = q.get("check_tools")
                missing_tools = set()
                if check_tools:
                    tool_calls = output.get("tool_calls", [])
                    tools_used = {tc.get("tool") for tc in tool_calls} if tool_calls else set()
                    missing_tools = set(check_tools) - tools_used
                    if missing_tools:
                        tools_ok = False

                if answer_ok and source_ok and tools_ok:
                    passed_count += 1
                    results.append(f"  + [{q['index']}] {question_text[:60]}...")
                else:
                    feedback = q.get("feedback")
                    if feedback:
                        reason = f"      Hint: {feedback}"
                    elif not answer_ok:
                        reason = (
                            f"      Answer: {answer[:100]}\n"
                            f"      Expected: {self._format_expected(expected)}"
                        )
                    elif not source_ok:
                        actual_src = output.get('source')
                        if not actual_src:
                            reason = "      'source' is null/missing — it is optional only for non-wiki questions; wiki questions must include a source file path"
                        else:
                            reason = f"      Source '{actual_src}' doesn't match expected"
                    elif not tools_ok:
                        reason = f"      Missing tools: {', '.join(missing_tools)}"
                    else:
                        reason = "      Unknown failure"
                    results.append(
                        f"  x [{q['index']}] {question_text[:60]}...\n{reason}"
                    )

            pass_rate = passed_count / total if total > 0 else 0
            summary = f"{passed_count}/{total} passed ({pass_rate:.0%})"
            detail_text = "\n".join(results)
            full_details = f"Agent eval: {summary}\n{detail_text}"

            return pass_rate >= min_pass_rate, full_details

        except subprocess.TimeoutExpired:
            return False, "Clone timed out"
        except Exception as e:
            return False, f"Agent eval error: {str(e)}"
        finally:
            if proxy_server:
                proxy_server.shutdown()
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _start_relay_proxy(self, target_ip: str, target_port: int):
        """Start a local HTTP proxy that forwards requests through the relay.

        Returns (port, server) — the server runs in a background thread.
        The proxy allows the sandbox container to reach the student VM's
        backend via http://host.docker.internal:{port}.
        """
        import os
        import random
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler

        import requests as req_lib

        relay_url = os.environ.get("RELAY_URL", "http://dashboard:8000/relay/check")
        relay_token = os.environ.get("RELAY_TOKEN", "")

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self._proxy("GET")

            def do_POST(self):
                self._proxy("POST")

            def do_PUT(self):
                self._proxy("PUT")

            def do_DELETE(self):
                self._proxy("DELETE")

            def _proxy(self, method):
                target_url = f"http://{target_ip}:{target_port}{self.path}"
                headers = {}
                for key, value in self.headers.items():
                    if key.lower() not in ("host", "transfer-encoding", "connection"):
                        headers[key] = value

                body = None
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length).decode("utf-8", errors="replace")

                try:
                    resp = req_lib.post(
                        relay_url,
                        json={
                            "url": target_url,
                            "method": method,
                            "headers": headers,
                            "body": body,
                            "timeout": 20,
                        },
                        headers={"Authorization": f"Bearer {relay_token}"},
                        timeout=35,
                    )
                    data = resp.json()
                    status = data.get("status_code", 502)
                    resp_body = data.get("body", "").encode()
                except Exception as e:
                    status = 502
                    resp_body = f'{{"error": "{str(e)}"}}'.encode()

                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            def log_message(self, format, *args):
                pass  # Suppress access logs

        port = random.randint(43000, 49000)
        server = HTTPServer(("0.0.0.0", port), ProxyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return port, server

    # NOTE: _ssh_check_via_relay is defined earlier in this class (with retry logic)

    def check_agent_eval_ssh(
        self, eval_lab: str,
        include_bot_only: bool = True,
        bot_only_exclusively: bool = False,
        max_tier: int = 3,
        min_pass_rate: float = 0.75,
        timeout_per_question: int = 90,
        sample_per_class: int = 0,
        use_cache: bool = False,
    ) -> Tuple[bool, str]:
        """Run agent evaluation via SSH on the student's VM.

        Instead of cloning the repo and running in a Docker sandbox,
        SSH into the student's VM where their agent.py and Qwen Code API
        are already set up. Each question is run as a separate SSH call
        through the relay worker (120s cap per call).
        """
        import json
        import os
        import time
        import yaml

        # Load eval questions
        specs_dir = os.path.join(os.path.dirname(__file__), '..', 'specs')
        eval_file = os.path.join(specs_dir, f"{eval_lab}-eval.yaml")
        if not os.path.exists(eval_file):
            return False, f"Eval file not found: {eval_lab}-eval.yaml"

        with open(eval_file) as f:
            all_questions = yaml.safe_load(f) or []

        questions = []
        for q in all_questions:
            if bot_only_exclusively and not q.get("bot_only", False):
                continue
            elif not include_bot_only and q.get("bot_only", False):
                continue
            if q.get("tier", 1) > max_tier:
                continue
            questions.append(q)
        questions.sort(key=lambda q: q["index"])

        if sample_per_class > 0:
            questions = _sample_eval_questions(questions, sample_per_class)

        if not questions:
            return False, "No questions matched the filter criteria"

        server_ip = self._server_ip or os.environ.get("SERVER_IP", "")
        if not server_ip:
            return False, "SERVER_IP not set — cannot SSH to student VM"

        username = self._vm_username or "autochecker"
        ssh_timeout = 120  # relay cap

        # 1. Find agent.py — check expected location first, then search.
        # Only match agent.py at the repo root (not in subdirectories like
        # task1_solution/) to avoid running the wrong file.
        ok, result = self._ssh_check_via_relay(
            server_ip, 22, username,
            "if [ -f ~/se-toolkit-lab-6/agent.py ]; then"
            "  echo ~/se-toolkit-lab-6/agent.py;"
            " else"
            "  find $HOME -maxdepth 2 -path '*/se-toolkit-lab-6/agent.py' 2>/dev/null | head -1;"
            " fi",
            30,
        )
        if not ok or not result.get("stdout", "").strip():
            return False, (
                f"Could not find agent.py on VM {server_ip}. "
                "Make sure se-toolkit-lab-6 is cloned and agent.py exists."
            )
        agent_path = result["stdout"].strip().split("\n")[0]
        repo_dir = os.path.dirname(agent_path)

        # 2. Check for LLM creds: .env.agent.secret, .env.agent, or auto-detect from proxy
        ok, result = self._ssh_check_via_relay(
            server_ip, 22, username,
            f"if [ -f {repo_dir}/.env.agent.secret ]; then echo SECRET; "
            f"elif [ -f {repo_dir}/.env.agent ]; then echo PLAIN; "
            f"else echo MISSING; fi",
            15,
        )
        env_file_type = result.get("stdout", "").strip() if ok else "MISSING"
        if env_file_type == "SECRET":
            env_agent_file = ".env.agent.secret"
        elif env_file_type == "PLAIN":
            env_agent_file = ".env.agent"
        else:
            # Auto-detect: look for qwen-code-oai-proxy config
            ok2, result2 = self._ssh_check_via_relay(
                server_ip, 22, username,
                "cat $HOME/qwen-code-oai-proxy/.env 2>/dev/null || echo NO_PROXY_ENV",
                15,
            )
            proxy_env = result2.get("stdout", "").strip() if ok2 else ""

            if proxy_env and "NO_PROXY_ENV" not in proxy_env:
                # Parse proxy .env for API key
                proxy_vars = {}
                for line in proxy_env.split("\n"):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        proxy_vars[k.strip()] = v.strip().strip('"').strip("'")

                api_key = proxy_vars.get("QWEN_API_KEY") or proxy_vars.get("API_KEY") or "my-secret-qwen-key"
                # Detect proxy port
                ok3, result3 = self._ssh_check_via_relay(
                    server_ip, 22, username,
                    "ss -tlnp 2>/dev/null | grep node | head -1",
                    10,
                )
                port_line = result3.get("stdout", "").strip() if ok3 else ""
                # Extract port from ss output like "LISTEN 0 511 0.0.0.0:8080"
                proxy_port = "8080"  # default
                if port_line:
                    import re as _re
                    port_match = _re.search(r":(\d+)\s", port_line)
                    if port_match:
                        proxy_port = port_match.group(1)

                # Create .env.agent.secret automatically
                env_content = (
                    f"LLM_API_KEY={api_key}\\n"
                    f"LLM_API_BASE_URL=http://127.0.0.1:{proxy_port}/v1\\n"
                    f"LLM_API_BASE=http://127.0.0.1:{proxy_port}/v1\\n"
                    f"LLM_API_MODEL=qwen3-coder-plus\\n"
                    f"LLM_MODEL=qwen3-coder-plus\\n"
                )
                self._ssh_check_via_relay(
                    server_ip, 22, username,
                    f"printf '{env_content}' > {repo_dir}/.env.agent.secret",
                    10,
                )
                env_agent_file = ".env.agent.secret"
            else:
                return False, (
                    f"No LLM credentials found on VM. Either:\n"
                    f"1. Create {repo_dir}/.env.agent.secret with LLM_API_KEY, LLM_API_BASE_URL/LLM_API_BASE, LLM_API_MODEL/LLM_MODEL\n"
                    f"2. Or set up ~/qwen-code-oai-proxy with a .env file"
                )

        # 3. Pull latest code and ensure uv is available and deps are synced
        ok, result = self._ssh_check_via_relay(
            server_ip, 22, username,
            f"cd {repo_dir} && export PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:$PATH\" && "
            "git pull --ff-only --quiet 2>/dev/null; "
            "which uv && uv sync --quiet 2>&1 | tail -3",
            60,
        )
        if not ok or "uv" not in result.get("stdout", ""):
            return False, (
                f"uv not found on VM. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
            )

        # 4. Get student's LMS_API_KEY from bot env (or fallback)
        lms_api_key = self._lms_api_key or os.environ.get("STUDENT_LMS_API_KEY", "") or "my-secret-api-key"

        # 4b. Load cached passed results from previous runs (only if use_cache=True)
        cache_file = f"{repo_dir}/_eval_cache.json"
        cached_passes = {}  # index -> stdout of passed run
        if use_cache:
            ok_cache, cache_result = self._ssh_check_via_relay(
                server_ip, 22, username,
                f"cat {cache_file} 2>/dev/null || echo '{{}}'",
                10,
            )
            if ok_cache:
                try:
                    cached_passes = json.loads(cache_result.get("stdout", "{}").strip())
                except json.JSONDecodeError:
                    cached_passes = {}

        # 5. Run each question via separate SSH call (skip cached passes)
        agent_outputs = {}
        for qi, q in enumerate(questions):
            idx = q["index"]

            # Skip questions that passed in a previous run
            if cached_passes.get(str(idx)):
                agent_outputs[str(idx)] = {"rc": 0, "stdout": cached_passes[str(idx)], "stderr": "", "cached": True}
                continue

            question_text = q["question"]
            # Escape single quotes for shell
            escaped_q = question_text.replace("'", "'\"'\"'")

            cmd = (
                f"cd {repo_dir} && "
                f"export PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:$PATH\" && "
                f"set -a && . <(tr -d '\\r' < {env_agent_file}) && set +a && "
                f"export LMS_API_KEY='{lms_api_key}' && "
                f"export AGENT_API_BASE_URL='http://localhost:42002' && "
                f"uv run agent.py '{escaped_q}' 2>/dev/null"
            )

            ok, result = self._ssh_check_via_relay(
                server_ip, 22, username, cmd, ssh_timeout,
            )

            stdout = result.get("stdout", "").strip() if ok else ""
            stderr = result.get("stderr", "").strip() if ok else result.get("error", "")
            exit_code = result.get("exit_code", -1) if ok else -1

            if not ok and "timeout" in result.get("error", "").lower():
                agent_outputs[str(idx)] = {"rc": -1, "stdout": "", "stderr": "timeout"}
            elif not ok:
                agent_outputs[str(idx)] = {"rc": exit_code, "stdout": stdout[:65536], "stderr": stderr[-500:]}
            else:
                agent_outputs[str(idx)] = {"rc": exit_code, "stdout": stdout[:65536], "stderr": stderr[-500:]}

            # Small delay between questions to avoid overwhelming the relay
            if qi < len(questions) - 1:
                time.sleep(1)

        # 6. Grade results (same logic as clone_and_run)
        passed_count = 0
        total = len(questions)
        results = []

        for q in questions:
            question_text = q["question"]
            expected = q.get("expected", {})
            idx = str(q["index"])

            ao = agent_outputs.get(idx)
            if not ao:
                results.append(f"  x [{q['index']}] Agent did not produce results")
                continue

            if ao["stderr"] == "timeout":
                results.append(f"  x [{q['index']}] Agent timed out ({ssh_timeout}s)")
                continue

            if ao["rc"] != 0:
                stderr_preview = ao["stderr"][:100]
                results.append(
                    f"  x [{q['index']}] Agent exited with code "
                    f"{ao['rc']}: {stderr_preview}"
                )
                continue

            stdout = ao["stdout"]
            if not stdout:
                results.append(f"  x [{q['index']}] Agent produced no output")
                continue

            # Agent may print extra lines; take the last JSON line
            json_line = ""
            for line in reversed(stdout.split("\n")):
                line = line.strip()
                if line.startswith("{"):
                    json_line = line
                    break

            if not json_line:
                results.append(f"  x [{q['index']}] No JSON in output: {stdout[:100]}")
                continue

            try:
                output = json.loads(json_line)
            except json.JSONDecodeError:
                results.append(f"  x [{q['index']}] Invalid JSON: {json_line[:100]}")
                continue

            answer = output.get("answer", "")
            if not answer:
                results.append(f"  x [{q['index']}] Missing 'answer' field")
                continue

            # Match answer
            rubric = q.get("rubric")
            if rubric:
                answer_ok = self._llm_judge(answer, rubric)
                if not answer_ok and expected:
                    answer_ok = self._match_answer(answer, expected)
            elif expected:
                answer_ok = self._match_answer(answer, expected)
            else:
                answer_ok = False

            # Check source
            source_ok = True
            expected_source = q.get("expected_source")
            if expected_source:
                source = output.get("source", "")
                if not source or not self._match_answer(source, expected_source):
                    source_ok = False

            # Check tools
            tools_ok = True
            check_tools = q.get("check_tools")
            missing_tools = set()
            if check_tools:
                tool_calls = output.get("tool_calls", [])
                tools_used = {tc.get("tool") for tc in tool_calls} if tool_calls else set()
                missing_tools = set(check_tools) - tools_used
                if missing_tools:
                    tools_ok = False

            if answer_ok and source_ok and tools_ok:
                passed_count += 1
                is_cached = agent_outputs.get(idx, {}).get("cached")
                cache_label = " (cached)" if is_cached else ""
                results.append(f"  + [{q['index']}] {question_text[:60]}...{cache_label}")
                # Cache the stdout for this passed question
                if not is_cached:
                    cached_passes[idx] = agent_outputs[idx]["stdout"]
            else:
                feedback = q.get("feedback")
                if feedback:
                    reason = f"      Hint: {feedback}"
                elif not answer_ok:
                    reason = (
                        f"      Answer: {answer[:100]}\n"
                        f"      Expected: {self._format_expected(expected)}"
                    )
                elif not source_ok:
                    actual_src = output.get('source')
                    if not actual_src:
                        reason = "      'source' is null/missing — it is optional only for non-wiki questions; wiki questions must include a source file path"
                    else:
                        reason = f"      Source '{actual_src}' doesn't match expected"
                elif not tools_ok:
                    reason = f"      Missing tools: {', '.join(missing_tools)}"
                else:
                    reason = "      Unknown failure"
                results.append(
                    f"  x [{q['index']}] {question_text[:60]}...\n{reason}"
                )

        # Save updated cache to student's VM (only if use_cache=True)
        if use_cache and cached_passes:
            import base64
            cache_b64 = base64.b64encode(json.dumps(cached_passes).encode()).decode()
            self._ssh_check_via_relay(
                server_ip, 22, username,
                f"echo '{cache_b64}' | base64 -d > {cache_file}",
                10,
            )

        pass_rate = passed_count / total if total > 0 else 0
        summary = f"{passed_count}/{total} passed ({pass_rate:.0%})"
        detail_text = "\n".join(results)
        full_details = f"Agent eval: {summary}\n{detail_text}"

        return pass_rate >= min_pass_rate, full_details

    @staticmethod
    def _llm_judge(answer: str, rubric: str) -> bool:
        """Use an LLM to judge an open-ended answer against a rubric.

        Returns True if the answer scores >= 3/5.
        Uses LLM_JUDGE_API_KEY (falls back to OPENROUTER_API_KEY).
        Uses LLM_JUDGE_API_URL (falls back to LLM_API_URL).
        """
        import os
        api_key = os.environ.get("LLM_JUDGE_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return False  # Can't judge without API key — fail gracefully

        try:
            from .llm_analyzer import _call_llm_api
            judge_api_url = os.environ.get("LLM_JUDGE_API_URL")
            prompt = (
                "You are a strict grader. Score the following answer 0-5 against the rubric.\n\n"
                f"### RUBRIC\n{rubric}\n\n"
                f"### ANSWER\n{answer}\n\n"
                "Return ONLY JSON: {\"score\": <0-5>, \"reason\": \"<brief reason>\"}"
            )
            result = _call_llm_api(
                api_key, prompt,
                model=os.environ.get("LLM_JUDGE_MODEL", "meta-llama/llama-4-scout:free"),
                api_url=judge_api_url,
            )
            return result.get("score", 0) >= 3
        except Exception:
            return False  # On error, fail gracefully

    @staticmethod
    def _match_answer(answer: str, expected: dict) -> bool:
        """Check if the answer satisfies the expected matching rule."""
        answer_lower = answer.lower()

        if "contains" in expected:
            return expected["contains"].lower() in answer_lower

        if "contains_all" in expected:
            return all(kw.lower() in answer_lower for kw in expected["contains_all"])

        if "any_of" in expected:
            return any(kw.lower() in answer_lower for kw in expected["any_of"])

        if "regex" in expected:
            return bool(re.search(expected["regex"], answer, re.IGNORECASE))

        if "numeric_gt" in expected:
            numbers = re.findall(r"\d+\.?\d*|\.\d+", answer)
            try:
                return any(float(n) > expected["numeric_gt"] for n in numbers)
            except ValueError:
                return False

        if "numeric_range" in expected:
            lo, hi = expected["numeric_range"]
            numbers = re.findall(r"\d+\.?\d*|\.\d+", answer)
            try:
                return any(lo <= float(n) <= hi for n in numbers)
            except ValueError:
                return False

        return False

    @staticmethod
    def _format_expected(expected: dict) -> str:
        """Human-readable description of the expected match."""
        if "contains" in expected:
            return f"contains \"{expected['contains']}\""
        if "contains_all" in expected:
            return f"contains all of {expected['contains_all']}"
        if "any_of" in expected:
            return f"any of {expected['any_of']}"
        if "regex" in expected:
            return f"matches /{expected['regex']}/"
        if "numeric_gt" in expected:
            return f"number > {expected['numeric_gt']}"
        if "numeric_range" in expected:
            return f"number in {expected['numeric_range']}"
        return str(expected)

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
            return None, (
                f"No issue found matching the required title pattern. "
                f"Create a GitHub issue whose title matches: {title_regex}"
            )

        issue_number = issue.get('number')
        if not issue_number:
            return None, "Issue has no number"

        prs = self._get_prs()
        close_pattern = rf'(?i)(closes|fixes|resolves)\s+#({issue_number})\b'

        for pr in prs:
            body = pr.get('body', '') or ''
            if re.search(close_pattern, body):
                return pr, f"Found PR #{pr.get('number')}: {pr.get('title', '')}"

        pr_count = len(prs)
        return None, (
            f"No PR found that closes issue #{issue_number} "
            f"(\"{issue.get('title', '')}\"). "
            f"Searched {pr_count} PR(s). "
            f"Add one of these keywords to your PR description: "
            f"'Closes #{issue_number}', 'Fixes #{issue_number}', or "
            f"'Resolves #{issue_number}'."
        )

    def check_issue_has_linked_pr(self, title_regex: str, merged: bool = True) -> Tuple[bool, str]:
        """Checks that there is a PR closing the issue found by title_regex."""
        pr, details = self._find_pr_for_issue(title_regex)
        if not pr:
            return False, details

        pr_num = pr.get('number')
        if merged and not pr.get('merged_at'):
            state = pr.get('state', 'unknown')
            return False, (
                f"PR #{pr_num} (\"{pr.get('title', '')}\") links to the issue "
                f"but is not merged (state: {state}). "
                f"Merge the PR on GitHub to close the issue."
            )

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
        import os
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
                min_matches = params.get('min_matches', 0)
                passed, details = self.check_glob_exists(patterns, min_matches=min_matches)
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
                    passed, details = self.check_commit_message_regex(pattern)
                    if passed: status = "PASS"
            
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
                    server_ip = self._server_ip or os.environ.get('SERVER_IP', 'localhost')
                    base_url_template = f"http://{server_ip}"
                
                # Replace {server_ip} if present
                if '{server_ip}' in base_url_template:
                    import os
                    server_ip = self._server_ip or os.environ.get('SERVER_IP', 'localhost')
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

                ssh_host = self._server_ip or os.environ.get('SERVER_IP', 'localhost')
                if base_url_template and '{server_ip}' in base_url_template:
                    pass  # ssh_host already set from SERVER_IP env

                command = params.get('command', 'echo ok')
                expect_regex = params.get('expect_regex')
                expect_exit = params.get('expect_exit', 0)
                username_param = params.get('username', 'autochecker')
                # Allow specs to reference the student's registered VM username
                if username_param == '__vm_username__' and self._vm_username:
                    username = self._vm_username
                else:
                    username = username_param
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

            elif check_type == "agent_eval":
                eval_lab = params.get('eval_lab', 'lab-06')
                include_bot_only = params.get('include_bot_only', True)
                bot_only_exclusively = params.get('bot_only_exclusively', False)
                max_tier = params.get('max_tier', 3)
                min_pass_rate = params.get('min_pass_rate', 0.75)
                timeout_per_q = params.get('timeout_per_question', 60)
                sample_per_class = params.get('sample_per_class', 0)
                use_cache = params.get('use_cache', False)

                # Use SSH-based eval when SERVER_IP is set (student has a VM)
                server_ip = self._server_ip or os.environ.get("SERVER_IP", "")
                use_ssh = bool(server_ip) and os.environ.get("RELAY_TOKEN")

                if use_ssh:
                    passed, details = self.check_agent_eval_ssh(
                        eval_lab=eval_lab,
                        include_bot_only=include_bot_only,
                        bot_only_exclusively=bot_only_exclusively,
                        max_tier=max_tier,
                        min_pass_rate=min_pass_rate,
                        timeout_per_question=timeout_per_q,
                        sample_per_class=sample_per_class,
                        use_cache=use_cache,
                    )
                else:
                    passed = False
                    details = (
                        "No VM registered. Please set your VM IP in the bot first: "
                        "send /start and follow the setup instructions to register your VM."
                    )
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
