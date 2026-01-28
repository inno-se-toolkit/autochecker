# autochecker/llm_analyzer.py
import json
import re
import time
import requests
import threading
from typing import Dict, List, Any, Optional
from .repo_reader import RepoReader
from .github_client import GitHubClient

# Глобальный семафор для ограничения одновременных запросов к Gemini API
# Максимум 1 одновременный запрос к API (строгое ограничение для избежания rate limit)
_api_semaphore = threading.Semaphore(1)
_last_request_time = 0
_request_lock = threading.Lock()
_MIN_REQUEST_INTERVAL = 1.0  # Минимальный интервал между запросами (секунды) - увеличено до 1 сек


def _call_gemini_api(gemini_api_key: str, prompt: str) -> Dict:
    """
    Вызывает Gemini API с заданным промптом.
    Возвращает распарсенный JSON ответ.
    """
    # Получаем список доступных моделей
    available_models = []
    try:
        list_models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_api_key}"
        list_response = requests.get(list_models_url, timeout=10)
        if list_response.status_code == 200:
            models_data = list_response.json()
            available_models = [
                model['name'].replace('models/', '')
                for model in models_data.get('models', [])
                if 'generateContent' in model.get('supportedGenerationMethods', [])
            ]
            preferred_models = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash-exp', 
                               'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
            available_models = sorted(available_models, key=lambda x: (
                preferred_models.index(x) if x in preferred_models else 999
            ))
    except Exception:
        pass
    
    if not available_models:
        available_models = [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-exp",
            "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro",
        ]
    
    api_url_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    last_error = None
    for idx, model_name in enumerate(available_models):
        with _api_semaphore:
            with _request_lock:
                global _last_request_time
                current_time = time.time()
                time_since_last = current_time - _last_request_time
                if time_since_last < _MIN_REQUEST_INTERVAL:
                    time.sleep(_MIN_REQUEST_INTERVAL - time_since_last)
                _last_request_time = time.time()
            
            if idx > 0:
                time.sleep(0.5)
            
            try:
                api_url = api_url_template.format(model=model_name)
                request_body = {
                    "contents": [{"parts": [{"text": prompt}]}]
                }
                headers = {"Content-Type": "application/json"}
                params = {"key": gemini_api_key}
                
                max_retries = 3
                retry_delay = 2
                response = None
                
                for attempt in range(max_retries):
                    try:
                        response = requests.post(
                            api_url, json=request_body, headers=headers,
                            params=params, timeout=60
                        )
                        
                        if response.status_code == 429:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (2 ** attempt)
                                time.sleep(wait_time)
                                continue
                            else:
                                raise requests.exceptions.HTTPError("429 Too Many Requests")
                        else:
                            response.raise_for_status()
                            break
                    except requests.exceptions.Timeout:
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay * (2 ** attempt))
                            continue
                        raise
                
                if response is None:
                    raise ValueError("Не удалось получить ответ от API")
                
                result = response.json()
                
                if 'candidates' in result and len(result['candidates']) > 0:
                    candidate = result['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        text = candidate['content']['parts'][0]['text']
                    else:
                        raise ValueError("Не удалось извлечь текст из ответа API")
                else:
                    raise ValueError("API вернул пустой ответ")
                
                cleaned_json = text.strip().replace("```json", "").replace("```", "").strip()
                
                try:
                    return json.loads(cleaned_json)
                except json.JSONDecodeError:
                    json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    raise
                    
            except requests.exceptions.RequestException as req_error:
                last_error = req_error
                if model_name == available_models[-1]:
                    raise
                continue
            except (json.JSONDecodeError, ValueError) as parse_error:
                last_error = parse_error
                if model_name == available_models[-1]:
                    raise
                continue
    
    if last_error:
        raise last_error
    raise RuntimeError("LLM call failed: все модели недоступны")


def run_llm_check(
    gemini_api_key: str,
    reader: RepoReader,
    check_id: str,
    check_params: Dict[str, Any],
    check_title: str = ""
) -> Dict:
    """
    Выполняет одну LLM проверку на основе параметров из спецификации.
    
    Args:
        gemini_api_key: API ключ для Gemini
        reader: RepoReader для чтения файлов репозитория
        check_id: ID проверки
        check_params: Параметры проверки (inputs, rubric, min_score)
        check_title: Заголовок проверки
    
    Returns:
        Dict с результатами: {id, status, score, details, reasons, quotes}
    """
    try:
        inputs = check_params.get('inputs', [])
        rubric = check_params.get('rubric', '')
        min_score = check_params.get('min_score', 3)
        
        # Собираем контент из inputs
        content_parts = []
        for input_spec in inputs:
            kind = input_spec.get('kind', 'file')
            if kind == 'file':
                path = input_spec.get('path', '')
                if path and reader.file_exists(path):
                    file_content = reader.read_file(path)
                    if file_content:
                        # Ограничиваем размер файла
                        if len(file_content) > 5000:
                            file_content = file_content[:5000] + "\n... (truncated)"
                        content_parts.append(f"### Содержимое файла: {path}\n```\n{file_content}\n```")
                    else:
                        content_parts.append(f"### Файл {path}: пустой или недоступен")
                else:
                    content_parts.append(f"### Файл {path}: не найден")
        
        if not content_parts:
            return {
                "id": check_id,
                "status": "ERROR",
                "score": 0,
                "details": "Не удалось получить контент для анализа",
                "reasons": ["Файлы для анализа не найдены"],
                "quotes": []
            }
        
        # Формируем промпт
        prompt = f"""Ты — строгий AI-ассистент для проверки студенческих работ.

### ЗАДАЧА
Проверь качество следующего контента по заданному критерию (rubric).

### КРИТЕРИЙ ОЦЕНКИ (Rubric)
{rubric}

### КОНТЕНТ ДЛЯ АНАЛИЗА
{chr(10).join(content_parts)}

### ИНСТРУКЦИИ
1. Внимательно прочитай rubric и контент
2. Оцени работу строго по критериям rubric
3. Выстави оценку от 0 до 5
4. Приведи конкретные аргументы и цитаты

### ФОРМАТ ОТВЕТА (ТОЛЬКО JSON)
{{
  "score": 0-5,
  "reasons": ["причина 1", "причина 2", ...],
  "quotes": [{{"text": "цитата из работы", "why": "почему это важно"}}]
}}

ВАЖНО: Верни ТОЛЬКО JSON, без дополнительного текста!
"""
        
        # Вызываем API
        result = _call_gemini_api(gemini_api_key, prompt)
        
        score = result.get('score', 0)
        reasons = result.get('reasons', [])
        quotes = result.get('quotes', [])
        
        # Определяем статус
        passed = score >= min_score
        status = "PASS" if passed else "FAIL"
        
        details = f"Оценка: {score}/{5} (минимум: {min_score})"
        if reasons:
            details += f"\nПричины: {'; '.join(reasons[:3])}"
        
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
        
    except Exception as e:
        return {
            "id": check_id,
            "status": "ERROR",
            "score": 0,
            "details": f"Ошибка LLM анализа: {str(e)[:200]}",
            "reasons": [f"Ошибка: {str(e)[:100]}"],
            "quotes": []
        }


def analyze_repo(
    gemini_api_key: str, 
    reader: RepoReader, 
    client: GitHubClient, 
    lab_spec=None, 
    repo_owner=None,
    check_results=None,
    plagiarism_score=None,
    plagiarism_source_student=None
) -> Dict:
    """
    Анализ репозитория с помощью Gemini через REST API.
    Используем прямые HTTP-запросы вместо библиотеки для избежания проблем с кодировкой.
    
    Args:
        check_results: Список результатов автоматических проверок (CheckResult)
        plagiarism_score: Оценка плагиата (0.0-1.0), если проверка плагиата была выполнена
        plagiarism_source_student: Имя студента, с которым обнаружена схожесть
    """

    # 1. Собираем контент для анализа - ЧИТАЕМ СОДЕРЖИМОЕ ФАЙЛОВ, а не только проверяем наличие
    readme_content = reader.read_file("README.md") or "README.md not found."
    
    # Безопасно обрабатываем содержимое файла
    if readme_content and isinstance(readme_content, bytes):
        try:
            readme_content = readme_content.decode('utf-8')
        except UnicodeDecodeError:
            readme_content = readme_content.decode('utf-8', errors='replace')
    
    # Ограничиваем длину для экономии токенов
    if len(readme_content) > 2000:
        readme_content = readme_content[:2000] + "... (truncated)"
    
    # Читаем содержимое ключевых файлов для анализа
    architecture_content = reader.read_file("docs/architecture.md") or ""
    roles_content = reader.read_file("docs/roles-and-skills.md") or ""
    reflection_content = reader.read_file("docs/reflection.md") or ""
    
    # Ограничиваем размер для экономии токенов, но оставляем достаточно для анализа
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
    
    # Получаем последний коммит для генерации ссылок
    commits = client.get_commits(branch=default_branch)
    commit_sha = commits[0]['sha'] if commits else 'main'
    commit_messages = "\n".join([c['commit']['message'] for c in commits[:20]]) if commits else "No commits found."
    
    # Безопасно обрабатываем commit messages
    if commit_messages and isinstance(commit_messages, bytes):
        try:
            commit_messages = commit_messages.decode('utf-8')
        except UnicodeDecodeError:
            commit_messages = commit_messages.decode('utf-8', errors='replace')
    
    # Ограничиваем длину
    if len(commit_messages) > 1000:
        commit_messages = commit_messages[:1000] + "... (truncated)"
    
    # Собираем код из коммитов и PR для анализа
    code_content_samples = []
    code_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.php', '.rb'}
    
    # Получаем список PR для анализа кода
    prs = client.get_pull_requests()
    if prs:
        for pr in prs[:3]:  # Анализируем первые 3 PR
            pr_number = pr.get('number')
            pr_url = pr.get('html_url', '')
            # Здесь можно получить diff из PR, но для начала используем файлы из репозитория
    
    # Читаем код-файлы из репозитория (исключая README, конфиги)
    all_files = reader.list_files() if hasattr(reader, 'list_files') else []
    
    if all_files:
        # Исключаем файлы документации и конфигов
        exclude_patterns = ['readme', 'license', 'changelog', 'package.json', 
                           'requirements.txt', 'dockerfile', '.gitignore', 
                           'docs/', '.github/']
        
        code_files = []
        for file_path_rel in all_files:
            file_path_lower = file_path_rel.lower()
            
            # Пропускаем исключенные файлы
            if any(pattern in file_path_lower for pattern in exclude_patterns):
                continue
            
            # Проверяем расширение файла
            if any(file_path_lower.endswith(ext) for ext in code_extensions):
                try:
                    content = reader.read_file(file_path_rel)
                    if content and len(content) > 50:  # Минимум 50 символов
                        # Ограничиваем размер каждого файла
                        truncated_content = content[:500] if len(content) > 500 else content
                        code_files.append({
                            'path': file_path_rel,
                            'content': truncated_content,
                            'size': len(content)
                        })
                        if len(code_files) >= 5:  # Максимум 5 файлов для анализа
                            break
                except:
                    continue
        
        if code_files:
            code_content_samples = code_files
    
    # Формируем текст с примерами кода
    code_samples_text = ""
    if code_content_samples:
        code_samples_text = "\n\nПримеры кода из репозитория:\n"
        for code_file in code_content_samples:
            code_samples_text += f"\n--- {code_file['path']} ---\n{code_file['content']}\n"
    
    # Формируем содержимое файлов для анализа
    task_files_content = ""
    if architecture_content:
        task_files_content += f"""
### СОДЕРЖИМОЕ docs/architecture.md (Task 1):
---
{architecture_content[:2500]}
---
"""
    if roles_content:
        task_files_content += f"""
### СОДЕРЖИМОЕ docs/roles-and-skills.md (Task 2):
---
{roles_content[:2500]}
---
"""
    if reflection_content:
        task_files_content += f"""
### СОДЕРЖИМОЕ docs/reflection.md (Task 3):
---
{reflection_content}
---
"""

    repo_content = f"""
Содержимое README.md (описание задания):
---
{readme_content}
---

{task_files_content}

История коммитов:
---
{commit_messages}
---
{code_samples_text}
"""

    # 2. Формулируем улучшенный промпт на основе системного промпта
    repo_name = lab_spec.repo_name if lab_spec else "unknown"
    owner = repo_owner or "unknown"
    
    # Формируем информацию о плагиате
    plagiarism_info = ""
    if plagiarism_score is not None and plagiarism_score > 0:
        plagiarism_info = f"""
### ⚠️ ВАЖНО: ОБНАРУЖЕН ПОДОЗРИТЕЛЬНЫЙ ПЛАГИАТ
- Схожесть с работой студента '{plagiarism_source_student or "неизвестный"}': {plagiarism_score*100:.1f}%
- Это указывает на возможное копирование кода. Учти это в своем анализе и будь особенно строг при оценке.
"""
    
    # Формируем список задач из спецификации с привязкой к проверкам
    lab_tasks_description = ""
    task_to_check_mapping = {}  # Словарь для связи задач с проверками
    if lab_spec and hasattr(lab_spec, 'checks'):
        tasks = []
        for i, check in enumerate(lab_spec.checks, 1):
            task_desc = f"Task {i}: {check.description or check.id}"
            if check.params:
                params_str = ", ".join([f"{k}={v}" for k, v in check.params.items()])
                task_desc += f" (Параметры: {params_str})"
            tasks.append(task_desc)
            # Сохраняем связь между задачей и проверкой
            task_to_check_mapping[i] = check.id
        lab_tasks_description = "\n".join(tasks) if tasks else "Задачи не указаны"
    else:
        lab_tasks_description = "Задачи не указаны в спецификации"
    
    # Формируем результаты автоматических проверок с явной привязкой к задачам
    automatic_checks_summary = ""
    if check_results:
        checks_list = []
        # Создаем словарь результатов по ID проверки
        results_by_id = {r.get('id'): r for r in check_results}
        
        # Формируем список с привязкой к задачам
        for task_num, check_id in task_to_check_mapping.items():
            result = results_by_id.get(check_id)
            if result:
                status_emoji = "✅" if result.get('status') == 'PASS' else "❌" if result.get('status') == 'FAIL' else "⚠️"
                status = result.get('status', 'UNKNOWN')
                description = result.get('description', '')
                details = result.get('details', '')
                checks_list.append(f"  Task {task_num} → {status_emoji} {check_id}: {status} - {description}")
                if details:
                    checks_list.append(f"     Детали: {details}")
            else:
                checks_list.append(f"  Task {task_num} → ⚠️ {check_id}: результат не найден")
        
        # Если есть результаты без привязки к задачам (на всякий случай)
        for result in check_results:
            check_id = result.get('id')
            if check_id not in task_to_check_mapping.values():
                status_emoji = "✅" if result.get('status') == 'PASS' else "❌" if result.get('status') == 'FAIL' else "⚠️"
                status = result.get('status', 'UNKNOWN')
                description = result.get('description', '')
                checks_list.append(f"  {status_emoji} {check_id}: {status} - {description}")
        
        automatic_checks_summary = "\n".join(checks_list) if checks_list else "Результаты проверок не найдены"
    else:
        automatic_checks_summary = "Результаты автоматических проверок не предоставлены"
    
    prompt = f"""Ты — строгий и технический AI-ассистент для проверки студенческих лабораторных работ.
Твоя задача — проанализировать работу студента и сгенерировать детальный отчет.

### ВХОДНЫЕ ДАННЫЕ:
1. Репозиторий: {repo_url or f'https://github.com/{owner}/{repo_name}'}
2. Commit SHA (для ссылок): {commit_sha}
3. Список задач (Tasks) - АНАЛИЗИРУЙ ТОЛЬКО ЭТИ ЗАДАЧИ:
{lab_tasks_description}

⚠️ ВАЖНО: В твоем ответе должно быть РОВНО {len(task_to_check_mapping)} задач в массиве task_analysis. НЕ создавай дополнительные задачи!

### ⚙️ РЕЗУЛЬТАТЫ АВТОМАТИЧЕСКИХ ПРОВЕРОК (ОБЯЗАТЕЛЬНО УЧТИ!):
{automatic_checks_summary}

{plagiarism_info}

### ИНФОРМАЦИЯ О РАБОТЕ:
{repo_content}

### КРИТИЧЕСКИ ВАЖНО - АНАЛИЗ СОДЕРЖИМОГО (НЕ НАЗВАНИЙ!):
- Ты видишь ПОЛНОЕ СОДЕРЖИМОЕ файлов docs/architecture.md, docs/roles-and-skills.md, docs/reflection.md
- НЕ обращай внимание на названия файлов, issues, PR, веток - это не важно!
- ФОКУСИРУЙСЯ ТОЛЬКО НА СОДЕРЖИМОМ: правильно ли выполнены задачи?
- Проверь, соответствует ли содержимое требованиям из README:

**Task 1 (Architecture - docs/architecture.md):**
  - Есть ли раздел "Product choice" с названием продукта, ссылкой и описанием?
  - Есть ли раздел "Motivation" с 3-4 предложениями о личном интересе?
  - Есть ли раздел "Main components" с минимум 5 компонентами и их описанием?
  - Есть ли диаграммы компонентов (mermaid или plantuml)?
  - Есть ли раздел "Data flow" с описанием типичного действия пользователя и диаграммой?
  - Есть ли раздел "Deployment" с описанием где живут компоненты и диаграммой?
  - Есть ли раздел "Knowledge Gaps" с минимум 2 вопросами/неопределенностями?

**Task 2 (Roles - docs/roles-and-skills.md):**
  - Есть ли раздел "Roles for components" с ролями для каждого компонента?
  - Есть ли раздел "Common skills across roles" со списком общих навыков?
  - Есть ли раздел "My chosen role" с названием роли, навыками которые есть/нет?
  - Упоминается ли roadmap.sh?
  - Есть ли раздел "Job market snapshot" с 5-7 ссылками на вакансии (hh.ru, linkedin.com)?
  - Есть ли анализ навыков из вакансий?

**Task 3 (Reflection - docs/reflection.md):**
  - Содержит ли 5-10 предложений?
  - Отвечает ли на вопросы: какая роль выбрана и почему?
  - Упоминает ли что-то новое об архитектуре продукта?
  - Упоминает ли релевантные темы курса (Git, Linux, Docker, REST, CI/CD, fullstack, data)?
  - Упоминает ли конкретный навык для улучшения?

- Оцени КАЧЕСТВО и ПОЛНОТУ содержимого, а не только его наличие
- Если содержимое неполное, некачественное или не соответствует требованиям - укажи это
- Цитируй конкретные части текста из файлов в своей аргументации
- Создавай ссылки на конкретные строки в GitHub для указания проблем

### КРИТИЧЕСКИЕ ПРАВИЛА ВЕРИФИКАЦИИ ССЫЛОК:
⚠️ Проверяй ВСЕ ссылки в работе студента по этим правилам:

1. **ОБНАРУЖЕНИЕ ПЛЕЙСХОЛДЕРОВ**: Если ссылка содержит 'example.com', 'username', 'repo-name', '<your-link>', '[link]', 'xxx', 'sample' - это ПРОВАЛ!
2. **ОБНАРУЖЕНИЕ GENERIC ССЫЛОК**: Ссылка только на домен (https://hh.kz или https://github.com) БЕЗ конкретной страницы - это ПРОВАЛ! Должны быть глубокие ссылки на конкретные страницы.
3. **СООТВЕТСТВИЕ КОНТЕКСТУ**: 
   - Ссылки на вакансии ДОЛЖНЫ быть с hh.ru, hh.kz, linkedin.com/jobs, indeed.com, и т.д.
   - Ссылки на roadmap.sh ДОЛЖНЫ вести на конкретную страницу roadmap.sh
   - Ссылки на GitHub ДОЛЖНЫ вести на конкретные репозитории, файлы или коммиты

Если ссылка не соответствует правилам:
- Result: ❌ ПРОВАЛ
- Argument: "Ссылка является плейсхолдером/шаблоном" или "Ссылка ведет только на главную страницу, не на конкретный ресурс"

### ИНСТРУКЦИИ ПО АНАЛИЗУ КОДА:
- Проанализируй качество кода в представленных файлах
- Оцени структуру, стиль, читаемость кода
- Проверь соответствие best practices для используемого языка программирования
- Если в коде есть проблемы, укажи конкретные места и предложи улучшения
- Ссылайся на конкретные строки кода, используя ссылки на GitHub
- НЕ просто проверяй наличие файлов, а анализируй их содержимое

### ФОРМАТ ОТВЕТА:
Ты должен вернуть JSON в следующем формате:
{{
  "verdict": "good" | "needs_improvement" | "poor",
  "reasons": ["причина 1", "причина 2", ...],
  "quotes": ["цитата 1", "цитата 2", ...],
  "task_analysis": [
    {{
      "task_number": 1,
      "task_name": "название задачи",
      "result": "✅ Выполнено" | "❌ Не выполнено",
      "argumentation": "детальная аргументация",
      "quotes": "конкретные цитаты из кода/текста",
      "link": "ссылка на GitHub (если применимо)"
    }},
    ...
  ]
}}

ВАЖНО: 
- verdict должен быть на английском: "good", "needs_improvement", "poor"
- reasons и argumentation могут быть на русском
- task_analysis должен содержать РОВНО {len(task_to_check_mapping)} элементов
- Каждый элемент task_analysis должен соответствовать задаче из списка выше
- Используй ссылки вида: https://github.com/{owner}/{repo_name}/blob/{commit_sha}/path/to/file#L<номер_строки>
"""

    # 3. Вызываем Gemini API
    try:
        # Получаем список доступных моделей
        available_models = []
        try:
            list_models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_api_key}"
            list_response = requests.get(list_models_url, timeout=10)
            if list_response.status_code == 200:
                models_data = list_response.json()
                # Фильтруем модели, которые поддерживают generateContent
                available_models = [
                    model['name'].replace('models/', '')
                    for model in models_data.get('models', [])
                    if 'generateContent' in model.get('supportedGenerationMethods', [])
                ]
                # Сортируем: сначала популярные модели
                preferred_models = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash-exp', 
                                   'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
                available_models = sorted(available_models, key=lambda x: (
                    preferred_models.index(x) if x in preferred_models else 999
                ))
                print(f"📋 Найдено доступных моделей: {len(available_models)}")
                if available_models:
                    print(f"   Используем: {', '.join(available_models[:5])}...")
        except Exception as list_error:
            print(f"⚠️  Не удалось получить список моделей: {list_error}")
        
        # Если не удалось получить список, используем стандартный набор
        if not available_models:
            available_models = [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.0-flash-exp",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
                "gemini-pro",
            ]
        
        # Формируем базовый URL без ключа (ключ передадим через параметры)
        api_url_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        
        last_error = None
        for idx, model_name in enumerate(available_models):
            # Ограничиваем количество одновременных запросов к API (глобально для всех потоков)
            with _api_semaphore:
                # Обеспечиваем минимальный интервал между запросами (глобально)
                with _request_lock:
                    global _last_request_time
                    current_time = time.time()
                    time_since_last = current_time - _last_request_time
                    if time_since_last < _MIN_REQUEST_INTERVAL:
                        sleep_time = _MIN_REQUEST_INTERVAL - time_since_last
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                    _last_request_time = time.time()
                
                # Небольшая задержка перед попыткой следующей модели (кроме первой)
                if idx > 0:
                    time.sleep(0.5)  # 500ms задержка между попытками разных моделей
                
                try:
                    # Формируем URL для API (без ключа в URL)
                    api_url = api_url_template.format(model=model_name)
                    
                    # Формируем тело запроса
                    request_body = {
                        "contents": [{
                            "parts": [{
                                "text": prompt
                            }]
                        }]
                    }
                    
                    # Отправляем запрос с ключом в параметрах и правильными заголовками
                    headers = {
                        "Content-Type": "application/json"
                    }
                    
                    # Передаем ключ через параметры запроса
                    params = {
                        "key": gemini_api_key
                    }
                    
                    # Пытаемся отправить запрос с повторными попытками при rate limiting
                    max_retries = 3
                    retry_delay = 2  # Начальная задержка в секундах
                    response = None
                    
                    for attempt in range(max_retries):
                        try:
                            response = requests.post(
                                api_url,
                                json=request_body,
                                headers=headers,
                                params=params,
                                timeout=60  # Увеличиваем timeout до 60 секунд
                            )
                            
                            # Если получили 429, ждем и повторяем
                            if response.status_code == 429:
                                if attempt < max_retries - 1:
                                    wait_time = retry_delay * (2 ** attempt)  # Экспоненциальная задержка
                                    print(f"⚠️  Rate limit (429) для модели {model_name}. Ожидание {wait_time} сек перед повтором...")
                                    time.sleep(wait_time)
                                    continue
                                else:
                                    # На последней попытке пробуем следующую модель
                                    raise requests.exceptions.HTTPError(f"429 Too Many Requests после {max_retries} попыток")
                            else:
                                # Для других статусов сразу проверяем
                                response.raise_for_status()
                                break  # Успешно получили ответ
                                
                        except requests.exceptions.Timeout:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (2 ** attempt)
                                print(f"⚠️  Timeout для модели {model_name}. Ожидание {wait_time} сек перед повтором...")
                                time.sleep(wait_time)
                                continue
                            else:
                                raise
                    
                    # Проверяем статус ответа (если еще не проверили)
                    if response is None:
                        raise ValueError("Не удалось получить ответ от API после всех попыток")
                    
                    # Парсим JSON ответ
                    result = response.json()
                    
                    # Извлекаем текст из ответа
                    if 'candidates' in result and len(result['candidates']) > 0:
                        candidate = result['candidates'][0]
                        if 'content' in candidate and 'parts' in candidate['content']:
                            text = candidate['content']['parts'][0]['text']
                        else:
                            raise ValueError("Не удалось извлечь текст из ответа API")
                    else:
                        raise ValueError("API вернул пустой ответ")
                    
                    # Очищаем JSON от markdown разметки
                    cleaned_json = (
                        text.strip()
                        .replace("```json", "")
                        .replace("```", "")
                        .strip()
                    )
                    
                    # Парсим JSON с обработкой ошибок экранирования
                    try:
                        analysis = json.loads(cleaned_json)
                    except json.JSONDecodeError as json_error:
                        # Пробуем исправить проблемы с экранированием в JSON
                        if "Invalid \\escape" in str(json_error) or "Invalid escape" in str(json_error):
                            print(f"⚠️  Попытка исправления экранирования в JSON...")
                            # Стратегия: Извлекаем JSON объект из текста с помощью regex
                            json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
                            if json_match:
                                json_text = json_match.group(0)
                                try:
                                    analysis = json.loads(json_text)
                                except:
                                    raise json_error
                            else:
                                raise json_error
                        else:
                            raise  # Если это не проблема с экранированием, пробрасываем дальше
                    
                    print(f"✅ Успешно использована модель: {model_name}")
                    return analysis
                    
                except requests.exceptions.RequestException as req_error:
                    last_error = req_error
                    error_msg = str(req_error)
                    
                    # Получаем детали ошибки из ответа, если есть
                    if hasattr(req_error, 'response') and req_error.response is not None:
                        try:
                            error_details = req_error.response.json()
                            error_msg = f"{error_msg}: {error_details}"
                            # Выводим детали ошибки для диагностики
                            status_code = req_error.response.status_code
                            if status_code == 404:
                                print(f"⚠️  Модель {model_name} не найдена. Детали: {error_details}")
                            elif status_code == 429:
                                # Для 429 не выводим детали, так как уже обработали выше
                                pass
                        except:
                            error_text = req_error.response.text[:300] if hasattr(req_error, 'response') and req_error.response else ""
                            error_msg = f"{error_msg}: {error_text}"
                            if hasattr(req_error, 'response') and req_error.response and req_error.response.status_code == 404:
                                print(f"⚠️  Модель {model_name} не найдена. Ответ: {error_text}")
                    
                    # Пропускаем ошибки 404 и пробуем следующую модель
                    # Для 429 тоже пробуем следующую модель (возможно, у неё другой лимит)
                    if "404" not in error_msg and "NOT_FOUND" not in error_msg:
                        # Не выводим сообщение для 429, так как уже обработали выше
                        if "429" not in error_msg and "Too Many Requests" not in error_msg:
                            print(f"⚠️  Ошибка при запросе к модели {model_name}: {error_msg[:200]}")
                        if model_name == available_models[-1]:  # Если это последняя модель
                            raise
                    continue
                except (json.JSONDecodeError, ValueError, KeyError) as parse_error:
                    last_error = parse_error
                    print(f"⚠️  Ошибка при парсинге ответа от модели {model_name}: {str(parse_error)[:100]}")
                    if model_name == available_models[-1]:  # Если это последняя модель
                        raise
                    continue

        # Если все модели не сработали, выбрасываем последнюю ошибку
        if last_error:
            raise last_error
        raise RuntimeError("LLM call failed: все модели недоступны")
        
    except Exception as e:
        # Безопасно обрабатываем ошибку с Unicode
        try:
            error_msg = str(e)
        except UnicodeEncodeError:
            error_msg = repr(e)  # Используем repr если str не работает
        
        print(f"🚨 Ошибка при вызове Gemini API или парсинге JSON: {error_msg}")
        return {
            "verdict": "analysis_failed",
            "reasons": [f"Произошла ошибка при анализе: {error_msg}"],
            "task_analysis": []
        }
