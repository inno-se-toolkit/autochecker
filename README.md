# Autochecker - Автоматическая проверка студенческих работ

Инструмент для автоматической проверки лабораторных работ студентов на GitHub и GitLab.

## Возможности

- ✅ **Автоматические проверки** - проверка структуры репозитория, файлов, коммитов, PR, issues
- 🤖 **LLM анализ** - качественная оценка контента с помощью Gemini AI
- 🔍 **Проверка плагиата** - обнаружение схожих работ между студентами
- 📊 **Детальные отчеты** - HTML и JSON отчеты для каждого студента
- 🚀 **Массовая обработка** - проверка сотен студентов параллельно
- 🔄 **Поддержка платформ** - GitHub и GitLab (включая self-hosted)

## Быстрый старт

### Установка

```bash
pip install -r requirements.txt
```

### Настройка

Создайте файл `.env`:
```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
GITLAB_TOKEN=glpat-xxxxxxxxxxxx
GEMINI_API_KEY=AIzaSy...
```

### Проверка одного студента

```bash
python3 main.py check -s StudentName -l lab-01 -p github
```

### Массовая проверка

```bash
python3 main.py batch -s students.csv -l lab-01 -p github
```

## Документация

- **[README_BATCH.md](README_BATCH.md)** - Подробная документация по массовой проверке
  - Формат файла со студентами
  - Параметры командной строки
  - Настройка проверки плагиата
  - Примеры для разных платформ

## Доступные команды

### `check` - Проверка одного студента
```bash
python3 main.py check -s StudentName -l lab-01 -p github
```

Опции:
- `-s, --student` - GitHub/GitLab username студента
- `-l, --lab` - Номер лабы (lab-01, lab-02, ...)
- `-p, --platform` - Платформа: github или gitlab
- `-b, --branch` - Ветка для проверки (по умолчанию из spec или main)
- `-o, --output` - Папка для результатов

### `batch` - Массовая проверка
```bash
python3 main.py batch -s students.csv -l lab-01 -p github
```

Опции:
- `-s, --students` - Файл со списком студентов (CSV/JSON/TXT)
- `-l, --lab` - Номер лабы (lab-01, lab-02, ...)
- `-p, --platform` - Платформа: github или gitlab
- `-w, --workers` - Параллельных потоков (2-3 рекомендуется)
- `--plagiarism/--no-plagiarism` - Проверка плагиата
- `--threshold` - Порог плагиата (0.0-1.0)
- `-b, --branch` - Ветка для проверки

### `labs` - Список доступных лаб
```bash
python3 main.py labs
```

## Структура проекта

```
autochecker/
├── main.py              # CLI интерфейс
├── autochecker/
│   ├── engine.py        # Движок проверок (code-based)
│   ├── llm_analyzer.py  # LLM анализ
│   ├── batch_processor.py  # Массовая обработка
│   ├── spec.py          # Парсер YAML спецификаций
│   └── ...
├── specs/               # YAML спецификации лаб
│   ├── lab-01.yaml
│   └── lab-02.yaml
└── results/             # Результаты проверок
```

## Типы проверок

### Code-based проверки (`runner: code`)
Автоматические проверки через Python код:
- Существование файлов/директорий
- Структура Markdown документов
- Регулярные выражения в файлах
- GitHub/GitLab API (issues, PRs, commits)
- И многое другое...

### LLM проверки (`runner: llm`)
Качественный анализ контента через Gemini AI:
- Оценка качества архитектурных документов
- Проверка содержания и полноты
- Анализ кода и дизайна API

## Спецификации лаб

Каждая лабораторная работа описывается в YAML файле (`specs/lab-XX.yaml`):

```yaml
id: lab-01
title: "Lab 01 – Products, Architecture & Roles"
repo_name: "lab-01-market-product-and-git"

discovery:
  default_branch: "main"

checks:
  - id: repo_exists
    title: "Repository exists"
    runner: code
    type: repo_exists
    is_required: true
    weight: 5
    params: {}
  
  - id: llm_arch_quality
    title: "LLM: architecture quality"
    runner: llm
    type: llm_judge
    is_required: true
    weight: 4
    params:
      inputs:
        - { kind: "file", path: "docs/architecture.md" }
      rubric: |
        Grade 0..5. Check quality...
      min_score: 3
```

## Результаты

После проверки создаются:
- `results/{student}/summary.html` - HTML отчет
- `results/{student}/results.jsonl` - Детальные результаты в JSON
- `results/batch_summary.html` - Сводка по всем студентам (для batch)
- `results/plagiarism_report.json` - Отчет о плагиате (если включен)

## Лицензия

[Укажите лицензию]

## Поддержка

[Контактная информация]