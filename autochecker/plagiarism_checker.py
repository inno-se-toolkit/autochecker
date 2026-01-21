# autochecker/plagiarism_checker.py
import hashlib
import fnmatch
import html
from typing import Dict, List, Tuple, Optional, Set
from pathlib import Path


class PlagiarismChecker:
    """
    Проверка на плагиат путем сравнения кода между студентами.
    
    Поддерживает настройку через PlagiarismConfig из спецификации:
    - include_paths: список путей/паттернов для проверки (если указан - проверяются только они)
    - exclude_paths: дополнительные пути для исключения
    - include_extensions: расширения файлов для проверки (если указан - используются только они)
    """
    
    # Стандартные расширения файлов с кодом
    DEFAULT_CODE_EXTENSIONS = {
        # Source code files
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp',
        '.cs', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala',
        '.html', '.css', '.scss', '.sass', '.less',
        # Scripts
        '.sh', '.bash', '.ps1', '.bat',
    }
    
    # Стандартные паттерны для исключения (одинаковые у всех студентов)
    DEFAULT_EXCLUDE_PATTERNS = [
        'readme*', 'license*', 'changelog*', 'changes*', 'history*',
        'package.json', 'package-lock.json', 'yarn.lock',
        'requirements.txt', 'pom.xml', 'build.gradle', 'go.mod', 'go.sum',
        'docker-compose.yml', 'dockerfile*',
        '.gitignore', '.env*', '.editorconfig',
        'docs/*', '.github/*', '.gitlab/*', '.vscode/*', '.idea/*',
        'ta_checklist*', 'checklist*',
        '*.md',  # Markdown файлы обычно одинаковые (задания)
        '*.yml', '*.yaml',  # Конфиги обычно шаблонные
    ]
    
    # Директории для игнорирования
    IGNORE_DIRECTORIES = ['.git/', 'node_modules/', '__pycache__/', '.venv/', 'venv/', '.idea/', '.vscode/']
    
    # Расширения бинарных файлов
    BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.exe', '.svg', '.ico', '.woff', '.ttf'}
    
    def __init__(self, 
                 include_paths: Optional[List[str]] = None,
                 exclude_paths: Optional[List[str]] = None,
                 include_extensions: Optional[List[str]] = None):
        """
        Args:
            include_paths: Пути/паттерны для проверки (если указан - только они)
            exclude_paths: Дополнительные пути для исключения
            include_extensions: Расширения для проверки (если указан - только они)
        """
        self._student_code_signatures: Dict[str, Dict[str, str]] = {}
        # Хранилище для содержимого файлов (для детального отчёта)
        self._student_file_contents: Dict[str, Dict[str, str]] = {}
        
        # Настройки фильтрации
        self._include_paths = include_paths or []
        self._exclude_paths = exclude_paths or []
        self._include_extensions = set(include_extensions) if include_extensions else None
    
    def _should_include_file(self, file_path: str) -> bool:
        """Проверяет, нужно ли включать файл в проверку плагиата."""
        file_path_lower = file_path.lower()
        file_name = file_path.split('/')[-1].lower()
        
        # 1. Проверяем игнорируемые директории
        if any(ignored in file_path_lower for ignored in self.IGNORE_DIRECTORIES):
            return False
        
        # 2. Проверяем бинарные файлы
        if any(file_path_lower.endswith(ext) for ext in self.BINARY_EXTENSIONS):
            return False
        
        # 3. Проверяем расширение файла
        code_extensions = self._include_extensions or self.DEFAULT_CODE_EXTENSIONS
        if not any(file_path_lower.endswith(ext) for ext in code_extensions):
            return False
        
        # 4. Если указаны include_paths - файл должен соответствовать хотя бы одному паттерну
        if self._include_paths:
            matches_include = False
            for pattern in self._include_paths:
                # Поддерживаем glob-паттерны
                if fnmatch.fnmatch(file_path_lower, pattern.lower()) or \
                   fnmatch.fnmatch(file_name, pattern.lower()) or \
                   file_path_lower.startswith(pattern.lower().rstrip('/*')):
                    matches_include = True
                    break
            if not matches_include:
                return False
        else:
            # Если include_paths не указан, используем стандартные исключения
            for pattern in self.DEFAULT_EXCLUDE_PATTERNS:
                if fnmatch.fnmatch(file_path_lower, pattern.lower()) or \
                   fnmatch.fnmatch(file_name, pattern.lower()):
                    return False
        
        # 5. Проверяем дополнительные исключения
        for pattern in self._exclude_paths:
            if fnmatch.fnmatch(file_path_lower, pattern.lower()) or \
               fnmatch.fnmatch(file_name, pattern.lower()) or \
               file_path_lower.startswith(pattern.lower().rstrip('/*')):
                return False
        
        return True
    
    def add_student_code(self, student_alias: str, reader) -> Dict[str, str]:
        """
        Добавляет код студента для сравнения.
        
        Args:
            student_alias: Имя студента
            reader: RepoReader для чтения файлов
        
        Returns:
            Словарь {путь_файла: хеш_содержимого}
        """
        signatures = {}
        contents = {}
        
        if not reader._zip_file:
            self._student_code_signatures[student_alias] = signatures
            self._student_file_contents[student_alias] = contents
            return signatures
        
        # Получаем список всех файлов в репозитории
        all_files = [f for f in reader._zip_file.namelist() 
                    if not f.endswith('/') and f.startswith(reader._root_dir)]
        
        for file_path in all_files:
            # Нормализуем путь (убираем root_dir)
            file_path_rel = file_path.replace(reader._root_dir, '')
            
            # Проверяем, нужно ли включать этот файл
            if not self._should_include_file(file_path_rel):
                continue
            
            try:
                content = reader.read_file(file_path_rel)
                if content and len(content.strip()) > 10:  # Минимум 10 символов
                    # Создаем хеш содержимого файла
                    content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
                    signatures[file_path_rel] = content_hash
                    # Сохраняем содержимое (ограничиваем до 5000 символов)
                    contents[file_path_rel] = content[:5000]
            except:
                continue
        
        self._student_code_signatures[student_alias] = signatures
        self._student_file_contents[student_alias] = contents
        return signatures
    
    def check_plagiarism(self, student_alias: str, threshold: float = 0.8) -> List[Dict]:
        """
        Проверяет плагиат для конкретного студента.
        Возвращает список подозрительных совпадений.
        threshold: порог схожести (0.0 - 1.0)
        """
        if student_alias not in self._student_code_signatures:
            return []
        
        student_files = self._student_code_signatures[student_alias]
        matches = []
        
        for other_student, other_files in self._student_code_signatures.items():
            if other_student == student_alias:
                continue
            
            # Считаем совпадения по хешам файлов
            common_files = set(student_files.keys()) & set(other_files.keys())
            if not common_files:
                continue
            
            identical_files = []
            similar_files = []
            
            for file_path in common_files:
                if student_files[file_path] == other_files[file_path]:
                    identical_files.append(file_path)
                else:
                    # Можно добавить более сложное сравнение (например, через difflib)
                    pass
            
            if identical_files:
                similarity = len(identical_files) / max(len(student_files), len(other_files))
                if similarity >= threshold:
                    matches.append({
                        "suspicious_student": other_student,
                        "similarity_score": similarity,
                        "identical_files": identical_files,
                        "common_files_count": len(common_files),
                        "total_files_student": len(student_files),
                        "total_files_other": len(other_files)
                    })
        
        # Сортируем по убыванию схожести
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)
        return matches
    
    def get_all_plagiarism_report(self, threshold: float = 0.8) -> Dict[str, List[Dict]]:
        """Получает отчет о плагиате для всех студентов."""
        all_matches = {}
        for student_alias in self._student_code_signatures.keys():
            matches = self.check_plagiarism(student_alias, threshold)
            if matches:
                all_matches[student_alias] = matches
        return all_matches
    
    def generate_detailed_html_report(self, output_dir: str, threshold: float = 0.5) -> str:
        """
        Генерирует детальный HTML-отчёт о плагиате с показом содержимого файлов.
        
        Returns:
            Путь к созданному файлу отчёта
        """
        report = self.get_all_plagiarism_report(threshold)
        
        if not report:
            return None
        
        # Собираем уникальные пары студентов (чтобы не дублировать)
        seen_pairs = set()
        unique_matches = []
        
        for student, matches in report.items():
            for match in matches:
                pair = tuple(sorted([student, match['suspicious_student']]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    unique_matches.append({
                        'student1': student,
                        'student2': match['suspicious_student'],
                        'similarity': match['similarity_score'],
                        'identical_files': match['identical_files'],
                        'total_files_1': match['total_files_student'],
                        'total_files_2': match['total_files_other']
                    })
        
        # Сортируем по схожести
        unique_matches.sort(key=lambda x: x['similarity'], reverse=True)
        
        # Генерируем HTML
        html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>🚨 Детальный отчёт о плагиате</title>
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            margin: 20px; 
            background: #f5f5f5;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #d32f2f; }
        .summary { 
            background: #fff; 
            padding: 20px; 
            border-radius: 8px; 
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .match-card {
            background: #fff;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            overflow: hidden;
        }
        .match-header {
            background: linear-gradient(135deg, #d32f2f, #f44336);
            color: white;
            padding: 15px 20px;
        }
        .match-header h2 { margin: 0; font-size: 1.3em; }
        .match-header .similarity {
            font-size: 2em;
            font-weight: bold;
        }
        .match-body { padding: 20px; }
        .file-comparison {
            margin-bottom: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            overflow: hidden;
        }
        .file-header {
            background: #263238;
            color: #80cbc4;
            padding: 10px 15px;
            font-family: monospace;
            font-size: 0.9em;
        }
        .file-content-wrapper {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0;
        }
        .file-content {
            padding: 15px;
            background: #fafafa;
            overflow-x: auto;
            max-height: 400px;
            overflow-y: auto;
            border-right: 1px solid #e0e0e0;
        }
        .file-content:last-child { border-right: none; }
        .file-content pre {
            margin: 0;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .student-label {
            background: #37474f;
            color: #fff;
            padding: 8px 15px;
            font-weight: bold;
            font-size: 0.85em;
        }
        .identical-badge {
            display: inline-block;
            background: #d32f2f;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            margin-left: 10px;
        }
        .stats { color: #666; margin-top: 5px; font-size: 0.9em; }
        .warning-box {
            background: #fff3e0;
            border-left: 4px solid #ff9800;
            padding: 15px;
            margin-bottom: 20px;
        }
        .legend {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .legend-color {
            width: 20px;
            height: 20px;
            border-radius: 4px;
        }
        .high { background: #d32f2f; }
        .medium { background: #ff9800; }
        .low { background: #ffc107; }
    </style>
</head>
<body>
<div class="container">
    <h1>🚨 Детальный отчёт о плагиате</h1>
    
    <div class="summary">
        <h3>📊 Статистика</h3>
        <p><b>Всего студентов проверено:</b> """ + str(len(self._student_code_signatures)) + """</p>
        <p><b>Обнаружено подозрительных пар:</b> <span style="color: #d32f2f; font-weight: bold;">""" + str(len(unique_matches)) + """</span></p>
        <p><b>Порог срабатывания:</b> """ + str(int(threshold * 100)) + """%</p>
        
        <div class="legend">
            <div class="legend-item"><div class="legend-color high"></div> Высокая схожесть (&gt;80%)</div>
            <div class="legend-item"><div class="legend-color medium"></div> Средняя схожесть (60-80%)</div>
            <div class="legend-item"><div class="legend-color low"></div> Низкая схожесть (&lt;60%)</div>
        </div>
    </div>
    
    <div class="warning-box">
        <b>⚠️ Внимание:</b> Этот отчёт показывает <b>идентичные файлы</b> между студентами.
        Идентичность означает, что содержимое файлов совпадает полностью (одинаковый MD5 хеш).
    </div>
"""
        
        for i, match in enumerate(unique_matches, 1):
            student1 = match['student1']
            student2 = match['student2']
            similarity = match['similarity']
            identical_files = match['identical_files']
            
            # Определяем цвет по уровню схожести
            if similarity >= 0.8:
                color_class = "high"
                level = "🔴 ВЫСОКАЯ"
            elif similarity >= 0.6:
                color_class = "medium"
                level = "🟠 СРЕДНЯЯ"
            else:
                color_class = "low"
                level = "🟡 НИЗКАЯ"
            
            html_content += f"""
    <div class="match-card">
        <div class="match-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h2>#{i} {student1} ↔ {student2}</h2>
                    <div class="stats">
                        {len(identical_files)} идентичных файлов из {match['total_files_1']} / {match['total_files_2']}
                    </div>
                </div>
                <div class="similarity">{similarity*100:.0f}%<br><small>{level}</small></div>
            </div>
        </div>
        <div class="match-body">
"""
            
            # Показываем каждый идентичный файл
            for file_path in identical_files:
                content1 = self._student_file_contents.get(student1, {}).get(file_path, "Содержимое недоступно")
                content2 = self._student_file_contents.get(student2, {}).get(file_path, "Содержимое недоступно")
                
                # Экранируем HTML
                content1_escaped = html.escape(content1)
                content2_escaped = html.escape(content2)
                
                # Обрезаем для отображения
                if len(content1_escaped) > 3000:
                    content1_escaped = content1_escaped[:3000] + "\n\n... [обрезано, файл слишком большой] ..."
                if len(content2_escaped) > 3000:
                    content2_escaped = content2_escaped[:3000] + "\n\n... [обрезано, файл слишком большой] ..."
                
                html_content += f"""
            <div class="file-comparison">
                <div class="file-header">
                    📄 {file_path} <span class="identical-badge">100% ИДЕНТИЧНЫ</span>
                </div>
                <div class="file-content-wrapper">
                    <div>
                        <div class="student-label">👤 {student1}</div>
                        <div class="file-content"><pre>{content1_escaped}</pre></div>
                    </div>
                    <div>
                        <div class="student-label">👤 {student2}</div>
                        <div class="file-content"><pre>{content2_escaped}</pre></div>
                    </div>
                </div>
            </div>
"""
            
            html_content += """
        </div>
    </div>
"""
        
        html_content += """
</div>
</body>
</html>
"""
        
        # Сохраняем файл
        output_path = Path(output_dir) / "plagiarism_detailed_report.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(output_path)
