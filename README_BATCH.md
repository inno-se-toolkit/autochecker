# Массовая проверка студентов

## Поддерживаемые платформы

- **GitHub** (по умолчанию)
- **GitLab** (включая self-hosted)

## Формат файла со студентами

### CSV формат (рекомендуется)
Создайте файл `students.csv`:
```csv
student_alias
Nurassyl28
student2
student3
student4
...
```

### JSON формат
Создайте файл `students.json`:
```json
["Nurassyl28", "student2", "student3", "student4"]
```

### TXT формат
Создайте файл `students.txt` (по одной строке):
```
Nurassyl28
student2
student3
student4
```

## Запуск массовой проверки

### GitHub (по умолчанию)
```bash
python3 main.py batch \
  --students students.csv \
  --lab lab-01 \
  --output results \
  --workers 2 \
  --plagiarism
```

### GitLab
```bash
python3 main.py batch \
  --students students.csv \
  --lab lab-01 \
  --platform gitlab \
  --gitlab-url https://gitlab.astanait.edu.kz \
  --output results \
  --workers 2 \
  --plagiarism
```

### Self-hosted GitLab
```bash
python3 main.py batch \
  --students students.csv \
  --lab lab-01 \
  --platform gitlab \
  --gitlab-url https://gitlab.mycompany.com \
  --output results \
  --workers 2
```

### С дополнительными опциями
```bash
python3 main.py batch \
  --students students.csv \
  --lab lab-02 \
  --platform github \
  --output results \
  --workers 3 \
  --plagiarism \
  --threshold 0.5 \
  --branch develop
```

**Примечание:**
- `--lab` - номер лабораторной работы (lab-01, lab-02, ...). Спецификация и имя репозитория определяются автоматически из конфигурации.
- `--spec` опция не нужна - спецификация загружается автоматически на основе `--lab`
- `--repo` опция не нужна - имя репозитория берется из спецификации

## Параметры

### Основные
- `--students` - путь к файлу со списком студентов (обязательно)
- `--repo` - имя репозитория для всех студентов (обязательно)
- `--spec` - путь к YAML спецификации (по умолчанию: specs/lab-01.yaml)
- `--output` - папка для результатов (по умолчанию: results)
- `--token` - GitHub/GitLab токен (или из `GITHUB_TOKEN`/`GITLAB_TOKEN`)

### Платформа
- `--platform` - `github` или `gitlab` (по умолчанию: github)
- `--gitlab-url` - URL GitLab сервера (по умолчанию: https://gitlab.com)

### Производительность
- `--workers` - количество параллельных потоков (рекомендуется 2-3 для избежания rate limit)

### Плагиат
- `--plagiarism/--no-plagiarism` - включить/выключить проверку на плагиат
- `--plagiarism-threshold` - порог схожести 0.0-1.0 (по умолчанию: 0.8)

### LLM анализ
- `--gemini-api-key` - ключ для LLM анализа (или из `GEMINI_API_KEY`)

## Настройка плагиата в спецификации

В YAML файле спецификации можно указать, какие файлы проверять на плагиат:

```yaml
plagiarism:
  enabled: true
  threshold: 0.7  # Порог схожести
  # Проверяем только файлы, созданные студентами
  include_paths:
    - "docs/architecture.md"
    - "docs/roles-and-skills.md"
    - "docs/reflection.md"
    - "src/*"  # Код студентов
  # Исключаем шаблоны и файлы преподавателя
  exclude_paths:
    - "README.md"
    - ".github/*"
  # Расширения для проверки (если не указано - стандартные код-файлы)
  include_extensions:
    - ".md"
    - ".py"
    - ".js"
```

### Примеры для разных лаб

**Lab 01 (текстовые документы):**
```yaml
plagiarism:
  include_paths:
    - "docs/architecture.md"
    - "docs/roles-and-skills.md"
  include_extensions:
    - ".md"
    - ".puml"
```

**Lab с кодом:**
```yaml
plagiarism:
  include_paths:
    - "src/*"
    - "app/*"
  exclude_paths:
    - "src/config.py"  # Шаблонный конфиг
  include_extensions:
    - ".py"
    - ".js"
    - ".ts"
```

## Переменные окружения

Создайте файл `.env`:
```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
GEMINI_API_KEY=AIzaSy...
```

## Результаты

После выполнения создаются:
- `results/batch_summary.html` - HTML сводка
- `results/batch_summary.json` - JSON статистика
- `results/plagiarism_report.json` - отчет о плагиате (если включен)
- `results/{student}/summary.html` - отчет для каждого студента
