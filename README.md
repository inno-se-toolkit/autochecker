# Autochecker - Автоматическая проверка студенческих работ

Инструмент для автоматической проверки лабораторных работ студентов на GitHub и GitLab.

## Возможности

- ✅ **Автоматические проверки** - проверка структуры репозитория, файлов, коммитов, PR, issues
- 🤖 **LLM анализ** - качественная оценка контента с помощью Qwen AI (через OpenRouter)
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

1. **Скопируйте пример файла конфигурации:**
   ```bash
   cp .env.example .env
   ```

2. **Получите GitHub Personal Access Token:**
   - Перейдите на https://github.com/settings/tokens
   - Нажмите "Generate new token" → "Generate new token (classic)"
   - Укажите название токена (например, "autochecker")
   - Выберите срок действия (рекомендуется: "No expiration" или "90 days")
   - Выберите необходимые права (scopes):
     - ✅ `repo` (Full control of private repositories) - для доступа к приватным репозиториям
     - ✅ `read:org` (Read org and team membership) - если проверяете репозитории организации
   - Нажмите "Generate token"
   - Скопируйте токен (начинается с `ghp_`) и вставьте в `.env` файл

3. **Получите GitLab Personal Access Token (опционально, если используете GitLab):**
   - Перейдите на https://gitlab.com/-/user_settings/personal_access_tokens
   - Укажите название токена (например, "autochecker")
   - Выберите срок действия
   - Выберите права (scopes):
     - ✅ `read_api` - для чтения данных через API
     - ✅ `read_repository` - для доступа к репозиториям
   - Нажмите "Create personal access token"
   - Скопируйте токен (начинается с `glpat-`) и вставьте в `.env` файл

4. **Получите OpenRouter API Key (для LLM проверок):**
   - Перейдите на https://openrouter.ai/keys
   - Зарегистрируйтесь или войдите в аккаунт
   - Нажмите "Create Key"
   - Скопируйте ключ (начинается с `sk-or-v1-`) и вставьте в `.env` файл
   - Пополните баланс на https://openrouter.ai/credits (для использования платных моделей)

5. **Отредактируйте `.env` файл:**
   ```env
   GITHUB_TOKEN=ghp_ваш_токен_здесь
   GITLAB_TOKEN=glpat-ваш_токен_здесь
   OPENROUTER_API_KEY=sk-or-v1-ваш_ключ_здесь
   ```

**Важно:** Файл `.env` уже добавлен в `.gitignore` и не будет закоммичен в репозиторий.

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
Качественный анализ контента через Qwen AI (через OpenRouter):
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

## Получение API ключей

### GitHub Personal Access Token

1. Перейдите на https://github.com/settings/tokens
2. Нажмите **"Generate new token"** → **"Generate new token (classic)"**
3. Заполните форму:
   - **Note**: Укажите название (например, "autochecker")
   - **Expiration**: Выберите срок действия (рекомендуется "No expiration" или "90 days")
   - **Select scopes**: Выберите необходимые права:
     - ✅ `repo` - Full control of private repositories (для доступа к приватным репозиториям)
     - ✅ `read:org` - Read org and team membership (если проверяете репозитории организации)
4. Нажмите **"Generate token"**
5. **Скопируйте токен** (начинается с `ghp_`) - он показывается только один раз!
6. Вставьте токен в файл `.env`:
   ```env
   GITHUB_TOKEN=ghp_ваш_скопированный_токен
   ```

### GitLab Personal Access Token (опционально)

1. Перейдите на https://gitlab.com/-/user_settings/personal_access_tokens
2. Заполните форму:
   - **Token name**: Укажите название (например, "autochecker")
   - **Expiration date**: Выберите срок действия
   - **Select scopes**: Выберите права:
     - ✅ `read_api` - для чтения данных через API
     - ✅ `read_repository` - для доступа к репозиториям
3. Нажмите **"Create personal access token"**
4. **Скопируйте токен** (начинается с `glpat-`)
5. Вставьте токен в файл `.env`:
   ```env
   GITLAB_TOKEN=glpat-ваш_скопированный_токен
   ```

### OpenRouter API Key (для LLM проверок)

1. Перейдите на https://openrouter.ai/keys
2. Зарегистрируйтесь или войдите в аккаунт
3. Нажмите **"Create Key"**
4. **Скопируйте ключ** (начинается с `sk-or-v1-`)
5. Вставьте ключ в файл `.env`:
   ```env
   OPENROUTER_API_KEY=sk-or-v1-ваш_скопированный_ключ
   ```
6. Пополните баланс на https://openrouter.ai/credits (для использования платных моделей)

**Примечание:** Бесплатные модели имеют строгие лимиты (2000 запросов/день, 60 запросов/минуту).

## Лицензия

[Укажите лицензию]

## Поддержка

[Контактная информация]