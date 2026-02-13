# autochecker/llm_analyzer.py
import json
import os
import re
import time
import requests
import threading
from typing import Dict, List, Any, Optional
from .repo_reader import RepoReader
from .github_client import GitHubClient

DEFAULT_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash-lite")

# Global semaphore to limit concurrent LLM API requests
# Max 1 concurrent API request (strict limit to avoid rate limit)
_api_semaphore = threading.Semaphore(1)
_last_request_time = 0
_request_lock = threading.Lock()
_MIN_REQUEST_INTERVAL = 2.0  # Minimum interval between requests (seconds) - increased to 2s to avoid rate limit
def _call_llm_api(openrouter_api_key: str, prompt: str, model: str = None) -> Dict:
    """
    Calls an LLM via OpenRouter API with the given prompt.
    Returns parsed JSON response.

    Args:
        openrouter_api_key: OpenRouter API key
        prompt: Prompt text
        model: Model to use (default: google/gemini-2.5-flash-lite)

    Returns:
        Dict with parsed JSON response
    """
    api_url = "https://openrouter.ai/api/v1/chat/completions"

    model = model or DEFAULT_MODEL
    models_to_try = [model]
    
    last_error = None
    for idx, model_name in enumerate(models_to_try):
        with _api_semaphore:
            with _request_lock:
                global _last_request_time
                current_time = time.time()
                time_since_last = current_time - _last_request_time
                if time_since_last < _MIN_REQUEST_INTERVAL:
                    time.sleep(_MIN_REQUEST_INTERVAL - time_since_last)
                _last_request_time = time.time()
            
            if idx > 0:
                time.sleep(1.0)  # Increased delay between model retry attempts
            
            try:
                request_body = {
                    "model": model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.3,  # Low temperature for more deterministic responses
                    "max_tokens": 4000
                }
                
                headers = {
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/autochecker",  # Optional, for tracking
                }
                
                max_retries = 3
                retry_delay = 5  # Initial retry delay increased to 5 seconds
                response = None
                
                for attempt in range(max_retries):
                    try:
                        response = requests.post(
                            api_url,
                            json=request_body,
                            headers=headers,
                            timeout=60
                        )
                        
                        # Handle 402 Payment Required
                        if response.status_code == 402:
                            error_msg = "402 Payment Required: Insufficient funds on your OpenRouter account or payment not configured."
                            error_msg += " Check your balance at https://openrouter.ai/credits"
                            raise requests.exceptions.HTTPError(error_msg)
                        
                        # Handle 429 Too Many Requests
                        if response.status_code == 429:
                            if attempt < max_retries - 1:
                                # Exponential backoff: 5, 10, 20 seconds
                                wait_time = retry_delay * (2 ** attempt)
                                print(f"⚠️  Rate limit (429). Waiting {wait_time} sec before retry...")
                                time.sleep(wait_time)
                                continue
                            else:
                                error_msg = "429 Too Many Requests: API request limit exceeded for OpenRouter API."
                                error_msg += " Wait a few minutes or increase the interval between requests."
                                raise requests.exceptions.HTTPError(error_msg)
                        
                        # Check errors for other status codes
                        if response.status_code >= 400:
                            response.raise_for_status()
                        break
                    except requests.exceptions.Timeout:
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)
                            print(f"⚠️  Timeout. Waiting {wait_time} sec before retry...")
                            time.sleep(wait_time)
                            continue
                        raise
                
                if response is None:
                    raise ValueError("Could not get API response")
                
                result = response.json()
                
                # Extract text from OpenRouter response
                if 'choices' in result and len(result['choices']) > 0:
                    choice = result['choices'][0]
                    if 'message' in choice and 'content' in choice['message']:
                        text = choice['message']['content']
                    else:
                        raise ValueError("Could not extract text from API response")
                else:
                    raise ValueError("API returned empty response")
                
                # Clean JSON from markdown markup
                cleaned_json = text.strip().replace("```json", "").replace("```", "").strip()

                # Fix invalid JSON escape sequences from LLM output.
                # LLMs often echo regex patterns (e.g. \s, \[, \d) which are
                # not valid JSON escapes. The regex below matches either a valid
                # \\ pair (kept as-is) or a lone \ before an invalid char (doubled).
                def _fix_escape(m):
                    if m.group(0) == '\\\\':
                        return '\\\\'
                    return '\\\\' + m.group(0)[1:]
                cleaned_json = re.sub(r'\\\\|\\(?!["\\/bfnrtu])', _fix_escape, cleaned_json)

                # Parse JSON (with progressive fallbacks for common LLM mistakes)
                def _try_parse(s):
                    """Try parsing JSON, fixing trailing commas if needed."""
                    try:
                        return json.loads(s)
                    except json.JSONDecodeError:
                        # Fix trailing commas before } or ] (common LLM mistake)
                        fixed = re.sub(r',\s*([}\]])', r'\1', s)
                        return json.loads(fixed)

                try:
                    return _try_parse(cleaned_json)
                except json.JSONDecodeError:
                    # Try to extract JSON object from surrounding text
                    json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
                    if json_match:
                        return _try_parse(json_match.group(0))
                    raise
                    
            except requests.exceptions.RequestException as req_error:
                last_error = req_error
                if model_name == models_to_try[-1]:
                    raise
                continue
            except (json.JSONDecodeError, ValueError) as parse_error:
                last_error = parse_error
                if model_name == models_to_try[-1]:
                    raise
                continue
    
    if last_error:
        raise last_error
    raise RuntimeError("LLM API call failed: all models unavailable")


def run_llm_check(
    openrouter_api_key: str,
    reader: RepoReader,
    check_id: str,
    check_params: Dict[str, Any],
    check_title: str = "",
    client: Optional[Any] = None,
) -> Dict:
    """
    Runs a single LLM check based on parameters from the spec.
    Uses LLM via OpenRouter API.

    Args:
        openrouter_api_key: API key for OpenRouter
        reader: RepoReader for reading repository files
        check_id: Check ID
        check_params: Check parameters (inputs, rubric, min_score, model)
        check_title: Check title

    Returns:
        Dict with results: {id, status, score, details, reasons, quotes}
    """
    try:
        inputs = check_params.get('inputs', [])
        rubric = check_params.get('rubric', '')
        min_score = check_params.get('min_score', 3)
        
        # Collect content from inputs
        content_parts = []
        for input_spec in inputs:
            kind = input_spec.get('kind', 'file')
            if kind == 'file':
                path = input_spec.get('path', '')
                if path and reader.file_exists(path):
                    file_content = reader.read_file(path)
                    if file_content:
                        # Limit file size
                        if len(file_content) > 5000:
                            file_content = file_content[:5000] + "\n... (truncated)"
                        content_parts.append(f"### File content: {path}\n```\n{file_content}\n```")
                    else:
                        content_parts.append(f"### File {path}: empty or inaccessible")
                else:
                    content_parts.append(f"### File {path}: not found")
            elif kind == 'issue':
                # Get issue by role or title_regex
                role = input_spec.get('role', '')
                title_regex = input_spec.get('title_regex', '')
                
                if not client:
                    content_parts.append(f"### Issue ({role or title_regex}): client not available")
                    continue
                
                # Get list of issues
                issues = client.get_issues() if hasattr(client, 'get_issues') else []
                
                matching_issue = None
                if role == 'bug':
                    # Look for issue with [Bug] in title
                    for issue in issues:
                        if re.search(r'^\[Bug\]', issue.get('title', ''), re.IGNORECASE):
                            matching_issue = issue
                            break
                elif title_regex:
                    # Search by title_regex
                    for issue in issues:
                        if re.search(title_regex, issue.get('title', ''), re.IGNORECASE):
                            matching_issue = issue
                            break
                else:
                    # Take first issue if role not specified
                    if issues:
                        matching_issue = issues[0]
                
                if matching_issue:
                    issue_title = matching_issue.get('title', 'N/A')
                    issue_body = matching_issue.get('body', '') or ''
                    # Limit size
                    if len(issue_body) > 5000:
                        issue_body = issue_body[:5000] + "\n... (truncated)"
                    content_parts.append(f"### Issue: {issue_title}\n\n{issue_body}")
                else:
                    content_parts.append(f"### Issue ({role or title_regex}): not found")
        
        if not content_parts:
            return {
                "id": check_id,
                "status": "ERROR",
                "score": 0,
                "details": "Could not get content for analysis",
                "reasons": ["Files for analysis not found"],
                "quotes": []
            }
        
        prompt = f"""You are a strict AI assistant for grading student assignments.

### TASK
Evaluate the quality of the following content according to the rubric.

### RUBRIC
{rubric}

### CONTENT TO ANALYZE
{chr(10).join(content_parts)}

### INSTRUCTIONS
1. Carefully read the rubric and content
2. Grade the work strictly by rubric criteria
3. Assign a score from 0 to 5
4. Provide specific reasons and quotes

### RESPONSE FORMAT (JSON ONLY)
{{
  "score": 0-5,
  "reasons": ["reason 1", "reason 2", ...],
  "quotes": [{{"text": "quote from the work", "why": "why this matters"}}]
}}

IMPORTANT: Return ONLY JSON, no additional text! All text must be in English.
"""
        
        llm_model = check_params.get('model', DEFAULT_MODEL)
        result = _call_llm_api(openrouter_api_key, prompt, llm_model)
        
        score = result.get('score', 0)
        reasons = result.get('reasons', [])
        quotes = result.get('quotes', [])
        
        # Determine status
        passed = score >= min_score
        status = "PASS" if passed else "FAIL"
        
        details = f"Score: {score}/{5} (minimum: {min_score})"
        if reasons:
            details += f"\nReasons: {'; '.join(reasons[:3])}"
        
        return {
            "id": check_id,
            "status": status,
            "score": score,
            "min_score": min_score,
            "details": details,
            "reasons": reasons,
            "quotes": quotes,
            "description": check_title
        }
        
    except requests.exceptions.HTTPError as http_error:
        error_msg = str(http_error)
        # Improved messages for specific errors
        if "402" in error_msg or "Payment Required" in error_msg:
            user_msg = "402 Payment Required: Insufficient funds on your OpenRouter account or payment not configured. Check your balance at https://openrouter.ai/credits"
        elif "429" in error_msg or "Too Many Requests" in error_msg:
            user_msg = "429 Too Many Requests: API request limit exceeded for OpenRouter API. Wait a few minutes or increase the interval between requests."
        else:
            user_msg = error_msg[:200]
        
        return {
            "id": check_id,
            "status": "ERROR",
            "score": 0,
            "min_score": min_score,
            "details": f"Score: 0/5 (min: {min_score if min_score else 'None'})\nReasons: {user_msg}",
            "reasons": [user_msg],
            "quotes": [],
            "description": check_title
        }
    except Exception as e:
        error_msg = str(e)[:200]
        return {
            "id": check_id,
            "status": "ERROR",
            "score": 0,
            "min_score": min_score,
            "details": f"Score: 0/5 (min: {min_score if min_score else 'None'})\nReasons: Error: {error_msg}",
            "reasons": [f"Error: {error_msg}"],
            "quotes": [],
            "description": check_title
        }


def analyze_repo(
    openrouter_api_key: str, 
    reader: RepoReader, 
    client: GitHubClient, 
    lab_spec=None, 
    repo_owner=None,
    check_results=None,
    plagiarism_score=None,
    plagiarism_source_student=None
) -> Dict:
    """
    Analyzes repository using LLM via OpenRouter API.

    Args:
        openrouter_api_key: OpenRouter API Key
        reader: Reader for accessing files
        client: Client for accessing GitHub/GitLab API
    """

    # 1. Collect content for analysis - READ FILE CONTENTS, not just check existence
    readme_content = reader.read_file("README.md") or "README.md not found."
    
    # Safely process file content
    if readme_content and isinstance(readme_content, bytes):
        try:
            readme_content = readme_content.decode('utf-8')
        except UnicodeDecodeError:
            readme_content = readme_content.decode('utf-8', errors='replace')
    
    # Limit length to save tokens
    if len(readme_content) > 2000:
        readme_content = readme_content[:2000] + "... (truncated)"
    
    # Read key file contents for analysis
    architecture_content = reader.read_file("docs/architecture.md") or ""
    roles_content = reader.read_file("docs/roles-and-skills.md") or ""
    reflection_content = reader.read_file("docs/reflection.md") or ""
    
    # Limit size to save tokens, but leave enough for analysis
    if architecture_content:
        if len(architecture_content) > 3000:
            architecture_content = architecture_content[:3000] + "... (truncated)"
    if roles_content:
        if len(roles_content) > 3000:
            roles_content = roles_content[:3000] + "... (truncated)"
    if reflection_content:
        if len(reflection_content) > 1000:
            reflection_content = reflection_content[:1000] + "... (truncated)"
    
    repo_info = client.get_repo_info()
    default_branch = repo_info.get('default_branch', 'main') if repo_info else 'main'
    repo_url = repo_info.get('html_url', '') if repo_info else ''
    
    # Get latest commit for link generation
    commits = client.get_commits(branch=default_branch)
    commit_sha = commits[0]['sha'] if commits else 'main'
    commit_messages = "\n".join([c['commit']['message'] for c in commits[:20]]) if commits else "No commits found."
    
    # Safely process commit messages
    if commit_messages and isinstance(commit_messages, bytes):
        try:
            commit_messages = commit_messages.decode('utf-8')
        except UnicodeDecodeError:
            commit_messages = commit_messages.decode('utf-8', errors='replace')
    
    # Limit length
    if len(commit_messages) > 1000:
        commit_messages = commit_messages[:1000] + "... (truncated)"
    
    # Collect code from commits and PRs for analysis
    code_content_samples = []
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.php', '.rb'}
    
    # Get list of PRs for code analysis
    prs = client.get_pull_requests()
    if prs:
        for pr in prs[:3]:  # Analyze first 3 PRs
            pr_number = pr.get('number')
            pr_url = pr.get('html_url', '')
            # Could get diff from PR here, but for now use files from repository
    
    # Read code files from repository (excluding README, configs)
    all_files = reader.list_files() if hasattr(reader, 'list_files') else []
    
    if all_files:
        # Exclude documentation and config files
        exclude_patterns = ['readme', 'license', 'changelog', 'package.json', 
                           'requirements.txt', 'dockerfile', '.gitignore', 
                           'docs/', '.github/']
        
        code_files = []
        for file_path_rel in all_files:
            file_path_lower = file_path_rel.lower()
            
            # Skip excluded files
            if any(pattern in file_path_lower for pattern in exclude_patterns):
                continue
            
            # Check file extension
            if any(file_path_lower.endswith(ext) for ext in code_extensions):
                try:
                    content = reader.read_file(file_path_rel)
                    if content and len(content) > 50:  # Minimum 50 characters
                        # Limit size of each file
                        truncated_content = content[:500] if len(content) > 500 else content
                        code_files.append({
                            'path': file_path_rel,
                            'content': truncated_content,
                            'size': len(content)
                        })
                        if len(code_files) >= 5:  # Max 5 files for analysis
                            break
                except:
                    continue
        
        if code_files:
            code_content_samples = code_files
    
    # Build text with code samples
    code_samples_text = ""
    if code_content_samples:
        code_samples_text = "\n\nCode samples from repository:\n"
        for code_file in code_content_samples:
            code_samples_text += f"\n--- {code_file['path']} ---\n{code_file['content']}\n"
    
    # Build file contents for analysis
    task_files_content = ""
    if architecture_content:
        task_files_content += f"""
### CONTENT OF docs/architecture.md (Task 1):
---
{architecture_content[:2500]}
---
"""
    if roles_content:
        task_files_content += f"""
### CONTENT OF docs/roles-and-skills.md (Task 2):
---
{roles_content[:2500]}
---
"""
    if reflection_content:
        task_files_content += f"""
### CONTENT OF docs/reflection.md (Task 3):
---
{reflection_content}
---
"""

    repo_content = f"""
README.md content (assignment description):
---
{readme_content}
---

{task_files_content}

Commit history:
---
{commit_messages}
---
{code_samples_text}
"""

    # 2. Build improved prompt based on system prompt
    repo_name = lab_spec.repo_name if lab_spec else "unknown"
    owner = repo_owner or "unknown"
    
    # Build plagiarism information
    plagiarism_info = ""
    if plagiarism_score is not None and plagiarism_score > 0:
        plagiarism_info = f"""
### ⚠️ IMPORTANT: SUSPICIOUS PLAGIARISM DETECTED
- Similarity with student '{plagiarism_source_student or "unknown"}' work: {plagiarism_score*100:.1f}%
- This indicates possible code copying. Consider this in your analysis and be especially strict when grading.
"""
    
    # Build task list from spec with check mapping
    lab_tasks_description = ""
    task_to_check_mapping = {}  # Dict mapping tasks to checks
    if lab_spec and hasattr(lab_spec, 'checks'):
        tasks = []
        for i, check in enumerate(lab_spec.checks, 1):
            task_desc = f"Task {i}: {check.description or check.id}"
            if check.params:
                params_str = ", ".join([f"{k}={v}" for k, v in check.params.items()])
                task_desc += f" (Params: {params_str})"
            tasks.append(task_desc)
            # Save mapping between task and check
            task_to_check_mapping[i] = check.id
        lab_tasks_description = "\n".join(tasks) if tasks else "Tasks not specified"
    else:
        lab_tasks_description = "Tasks not specified in the spec"
    
    # Build automated check results with explicit task mapping
    automatic_checks_summary = ""
    if check_results:
        checks_list = []
        # Create results dict by check ID
        results_by_id = {r.get('id'): r for r in check_results}
        
        # Build list with task mapping
        for task_num, check_id in task_to_check_mapping.items():
            result = results_by_id.get(check_id)
            if result:
                status_emoji = "✅" if result.get('status') == 'PASS' else "❌" if result.get('status') == 'FAIL' else "⚠️"
                status = result.get('status', 'UNKNOWN')
                description = result.get('description', '')
                details = result.get('details', '')
                checks_list.append(f"  Task {task_num} → {status_emoji} {check_id}: {status} - {description}")
                if details:
                    checks_list.append(f"     Details: {details}")
            else:
                checks_list.append(f"  Task {task_num} → ⚠️ {check_id}: result not found")
        
        # If there are results not mapped to tasks (just in case)
        for result in check_results:
            check_id = result.get('id')
            if check_id not in task_to_check_mapping.values():
                status_emoji = "✅" if result.get('status') == 'PASS' else "❌" if result.get('status') == 'FAIL' else "⚠️"
                status = result.get('status', 'UNKNOWN')
                description = result.get('description', '')
                checks_list.append(f"  {status_emoji} {check_id}: {status} - {description}")
        
        automatic_checks_summary = "\n".join(checks_list) if checks_list else "Check results not found"
    else:
        automatic_checks_summary = "Automated check results not provided"
    
    prompt = f"""You are a strict, technical AI assistant for grading student lab assignments.
Your task is to analyze the student's work and generate a detailed report.

### INPUT DATA:
1. Repository: {repo_url or f'https://github.com/{owner}/{repo_name}'}
2. Commit SHA (for links): {commit_sha}
3. Task list — ANALYZE ONLY THESE TASKS:
{lab_tasks_description}

⚠️ IMPORTANT: Your response must contain EXACTLY {len(task_to_check_mapping)} tasks in the task_analysis array. Do NOT create additional tasks!

### ⚙️ AUTOMATED CHECK RESULTS (MUST BE CONSIDERED!):
{automatic_checks_summary}

{plagiarism_info}

### SUBMISSION CONTENT:
{repo_content}

### CRITICAL — ANALYZE CONTENT, NOT FILENAMES!
- You can see the FULL CONTENT of docs/architecture.md, docs/roles-and-skills.md, docs/reflection.md
- Do NOT focus on filenames, issues, PRs, or branches — focus on CONTENT
- Check whether the content meets the requirements from the README

### LINK VERIFICATION RULES:
⚠️ Verify ALL links in the student's work:
1. **Placeholder detection**: If a link contains 'example.com', 'username', 'repo-name', '<your-link>', '[link]', 'xxx', 'sample' — it's a FAIL!
2. **Generic link detection**: A link to just a domain (https://hh.kz or https://github.com) WITHOUT a specific page — FAIL! Must be deep links.
3. **Context match**: Job links must be from hh.ru, hh.kz, linkedin.com/jobs, etc. Roadmap links must point to specific roadmap.sh pages.

### RESPONSE FORMAT:
Return JSON in the following format:
{{
  "verdict": "good" | "needs_improvement" | "poor",
  "reasons": ["reason 1", "reason 2", ...],
  "quotes": ["quote 1", "quote 2", ...],
  "task_analysis": [
    {{
      "task_number": 1,
      "task_name": "task name",
      "result": "PASS" | "FAIL",
      "argumentation": "detailed reasoning",
      "quotes": "specific quotes from code/text",
      "link": "GitHub link (if applicable)"
    }},
    ...
  ]
}}

IMPORTANT:
- ALL text in the response MUST be in English
- task_analysis must contain EXACTLY {len(task_to_check_mapping)} elements
- Use links like: https://github.com/{owner}/{repo_name}/blob/{commit_sha}/path/to/file#L<line_number>
"""

    # 3. Call LLM API
    try:
        print(f"🤖 Running LLM analysis (OpenRouter)...")
        return _call_llm_api(openrouter_api_key, prompt)
        
    except Exception as e:
        # Safely handle Unicode error
        try:
            error_msg = str(e)
        except UnicodeEncodeError:
            error_msg = repr(e)  # Use repr if str doesn't work
        
        print(f"🚨 LLM API error: {error_msg}")
        return {
            "verdict": "analysis_failed",
            "reasons": [f"Analysis error: {error_msg}"],
            "task_analysis": []
        }
