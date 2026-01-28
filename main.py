# main.py
import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from autochecker.spec import load_spec
from autochecker.github_client import GitHubClient
from autochecker.gitlab_client import GitLabClient, create_client
from autochecker.repo_reader import RepoReader
from autochecker.engine import CheckEngine
from autochecker.reporter import Reporter

# Создаем приложение Typer
app = typer.Typer(help="🎓 Autochecker - Автоматическая проверка студенческих работ")

load_dotenv()  # Подхватываем токены из .env, если файл существует

# Конфигурация лабораторных работ
LAB_CONFIG = {
    "lab-01": {
        "name": "Lab 01 – Products, Architecture & Roles",
        "repo_suffix": "lab-01-market-product-and-git",
        "spec": "specs/lab-01.yaml",
        "ready": True
    },
    "lab-02": {
        "name": "Lab 02 — Understand, Improve, and Deploy a Backend Service",
        "repo_suffix": "lab-02-fix-and-deploy-backend",
        "spec": "specs/lab-02.yaml",
        "ready": True
    },
    "lab-03": {
        "name": "Lab 03 – (Coming soon)",
        "repo_suffix": "lab-03-tbd",
        "spec": "specs/lab-03.yaml",
        "ready": False
    },
    "lab-04": {
        "name": "Lab 04 – (Coming soon)",
        "repo_suffix": "lab-04-tbd",
        "spec": "specs/lab-04.yaml",
        "ready": False
    },
    "lab-05": {
        "name": "Lab 05 – (Coming soon)",
        "repo_suffix": "lab-05-tbd",
        "spec": "specs/lab-05.yaml",
        "ready": False
    },
    "lab-06": {
        "name": "Lab 06 – (Coming soon)",
        "repo_suffix": "lab-06-tbd",
        "spec": "specs/lab-06.yaml",
        "ready": False
    },
    "lab-07": {
        "name": "Lab 07 – (Coming soon)",
        "repo_suffix": "lab-07-tbd",
        "spec": "specs/lab-07.yaml",
        "ready": False
    },
    "lab-08": {
        "name": "Lab 08 – (Coming soon)",
        "repo_suffix": "lab-08-tbd",
        "spec": "specs/lab-08.yaml",
        "ready": False
    },
    "lab-09": {
        "name": "Lab 09 – (Coming soon)",
        "repo_suffix": "lab-09-tbd",
        "spec": "specs/lab-09.yaml",
        "ready": False
    },
    "lab-10": {
        "name": "Lab 10 – (Coming soon)",
        "repo_suffix": "lab-10-tbd",
        "spec": "specs/lab-10.yaml",
        "ready": False
    },
}


def select_platform() -> tuple:
    """Интерактивный выбор платформы."""
    print("\n" + "="*50)
    print("🌐 ВЫБОР ПЛАТФОРМЫ")
    print("="*50)
    print("  1. GitHub (github.com)")
    print("  2. GitLab (gitlab.astanait.edu.kz)")
    print("  3. GitLab (другой сервер)")
    print("-"*50)
    
    choice = input("Выберите платформу [1]: ").strip() or "1"
    
    if choice == "2":
        return "gitlab", "https://gitlab.astanait.edu.kz"
    elif choice == "3":
        url = input("Введите URL GitLab сервера: ").strip()
        return "gitlab", url
    else:
        return "github", "https://github.com"


def select_lab() -> dict:
    """Интерактивный выбор лабораторной работы."""
    print("\n" + "="*50)
    print("📚 ВЫБОР ЛАБОРАТОРНОЙ РАБОТЫ")
    print("="*50)
    
    for i, (lab_id, config) in enumerate(LAB_CONFIG.items(), 1):
        status = "✅" if config["ready"] else "🚧"
        print(f"  {i}. {status} {config['name']}")
    
    print("-"*50)
    choice = input("Выберите лабораторную работу [1]: ").strip() or "1"
    
    try:
        idx = int(choice) - 1
        lab_id = list(LAB_CONFIG.keys())[idx]
        config = LAB_CONFIG[lab_id]
        
        if not config["ready"]:
            print(f"⚠️  {config['name']} ещё не готова!")
            print("   Пока доступна только Lab 01.")
            return LAB_CONFIG["lab-01"]
        
        return config
    except (ValueError, IndexError):
        print("⚠️  Неверный выбор, используем Lab 01")
        return LAB_CONFIG["lab-01"]


@app.command()
def check(
    student: str = typer.Option(None, "--student", "-s", help="GitHub/GitLab username студента"),
    lab: str = typer.Option(None, "--lab", "-l", help="Номер лабы (lab-01, lab-02, ...)"),
    platform: str = typer.Option(None, "--platform", "-p", help="Платформа: github или gitlab"),
    gitlab_url: str = typer.Option("https://gitlab.astanait.edu.kz", "--gitlab-url", help="URL GitLab сервера"),
    output_dir: str = typer.Option("results", "--output", "-o", help="Папка для результатов"),
    token: str = typer.Option(None, envvar=["GITHUB_TOKEN", "GITLAB_TOKEN"], help="Access Token"),
    gemini_api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Gemini API Key"),
    branch: str = typer.Option(None, "--branch", "-b", help="Ветка для проверки (по умолчанию из spec или main)"),
):
    """
    🎯 Проверить одного студента.
    
    Примеры:
      python main.py check -s Nurassyl28 -l lab-01 -p github
      python main.py check  # интерактивный режим
    """
    # Проверяем токен
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITLAB_TOKEN")
    
    if not token:
        print("❌ Токен не найден! Добавьте GITHUB_TOKEN или GITLAB_TOKEN в .env")
        raise typer.Exit(code=1)
    
    # Интерактивный режим если параметры не указаны
    if not platform:
        platform, gitlab_url = select_platform()
    
    if not lab:
        lab_config = select_lab()
    else:
        lab_config = LAB_CONFIG.get(lab, LAB_CONFIG["lab-01"])
    
    if not student:
        platform_name = "GitLab" if platform == "gitlab" else "GitHub"
        print("\n" + "="*50)
        print(f"👤 СТУДЕНТ ({platform_name})")
        print("="*50)
        student = input("Введите username студента: ").strip()
    
    if not student:
        print("❌ Не указан студент!")
        raise typer.Exit(code=1)
    
    # Запускаем проверку
    repo_name = lab_config["repo_suffix"]
    spec_path = lab_config["spec"]
    
    print("\n" + "="*50)
    print("🚀 ЗАПУСК ПРОВЕРКИ")
    print("="*50)
    print(f"  Платформа: {platform}")
    print(f"  Студент:   {student}")
    print(f"  Репо:      {repo_name}")
    print(f"  Лаба:      {lab_config['name']}")
    print("="*50 + "\n")
    
    _run_single_check(
        student_alias=student,
        repo_name=repo_name,
        spec_path=spec_path,
        token=token,
        gemini_api_key=gemini_api_key,
        output_dir=output_dir,
        platform=platform,
        gitlab_url=gitlab_url,
        branch=branch
    )


def _run_single_check(student_alias, repo_name, spec_path, token, gemini_api_key, 
                      output_dir, platform, gitlab_url, branch=None):
    """Внутренняя функция для проверки одного студента."""
    try:
        if not Path(spec_path).exists():
            print(f"❌ Файл спецификации не найден: {spec_path}")
            raise typer.Exit(code=1)

        lab_spec = load_spec(str(spec_path))
        lab_spec.repo_name = repo_name

        # Подготовка
        Path(output_dir).mkdir(exist_ok=True)
        student_results_dir = Path(output_dir) / student_alias
        student_results_dir.mkdir(exist_ok=True)
        
        for old_file in ['summary.html', 'results.jsonl']:
            old_path = student_results_dir / old_file
            if old_path.exists():
                old_path.unlink()

        # Создаем клиент
        client = create_client(
            platform=platform,
            token=token,
            repo_owner=student_alias,
            repo_name=repo_name,
            gitlab_url=gitlab_url
        )

        # Проверяем доступность
        repo_info = client.get_repo_info()
        if not repo_info:
            print(f"  ❌ Репозиторий не найден или недоступен")
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Репозиторий не найден")
            raise typer.Exit()
        
        if repo_info.get('private'):
            print(f"  ❌ Репозиторий приватный")
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Репозиторий приватный")
            raise typer.Exit()

        # Скачиваем архив
        reader = RepoReader(
            owner=student_alias, 
            repo_name=repo_name, 
            token=token,
            platform=platform,
            gitlab_url=gitlab_url
        )
        
        # Получаем branch: CLI override > spec file > repo default
        check_branch = branch
        if not check_branch and hasattr(lab_spec, 'discovery') and lab_spec.discovery:
            check_branch = lab_spec.discovery.get('default_branch')
        
        # Запускаем проверки
        engine = CheckEngine(client, reader, branch=check_branch)
        results = []
        for check_spec in lab_spec.checks:
            check_description = check_spec.title or check_spec.description or check_spec.id
            print(f"  ▶️  {check_description}")
            result = engine.run_check(check_spec.id, check_spec.type, check_spec.params, check_description)
            status_icon = "✅" if result['status'] == 'PASS' else "❌" if result['status'] == 'FAIL' else "⚠️"
            print(f"     {status_icon} {result['status']}")
            results.append(result)

        # LLM анализ
        llm_analysis = None
        if gemini_api_key:
            try:
                from autochecker.llm_analyzer import analyze_repo
                print("\n🤖 Запуск LLM анализа...")
                llm_analysis = analyze_repo(
                    gemini_api_key, reader, client,
                    lab_spec=lab_spec, 
                    repo_owner=student_alias,
                    check_results=results
                )
            except Exception as e:
                llm_analysis = {
                    "verdict": "анализ_провален",
                    "reasons": [f"Ошибка: {str(e)[:100]}"],
                }

        # Сохраняем отчет
        reporter = Reporter(
            student_alias=student_alias, 
            results=results, 
            repo_url=repo_info.get("html_url"),
            llm_analysis=llm_analysis
        )
        reporter.write_jsonl(student_results_dir)
        reporter.write_html(student_results_dir)

        # Статистика
        passed = sum(1 for r in results if r['status'] == 'PASS')
        total = len(results)
        score = (passed / total * 100) if total > 0 else 0
        
        print(f"\n{'='*50}")
        print(f"📊 РЕЗУЛЬТАТ: {score:.1f}% ({passed}/{total})")
        print(f"📄 Отчет: {student_results_dir}/summary.html")
        print(f"{'='*50}\n")

    except typer.Exit:
        raise
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@app.command()
def run(
    spec_path: Path = typer.Option("specs/lab-01.yaml", "--spec", help="Путь к файлу спецификации .yaml"),
    output_dir: str = typer.Option("results", "--output", help="Папка для сохранения результатов"),
    token: str = typer.Option(None, envvar=["GITHUB_TOKEN", "GITLAB_TOKEN"], help="GitHub/GitLab Personal Access Token. Задайте через GITHUB_TOKEN или GITLAB_TOKEN в .env"),
    gemini_api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Gemini API Key. Можно также задать через переменную окружения GEMINI_API_KEY"),
    platform: str = typer.Option("github", "--platform", help="Платформа: github или gitlab"),
    gitlab_url: str = typer.Option("https://gitlab.com", "--gitlab-url", help="URL GitLab сервера (для self-hosted GitLab)"),
):
    """
    [Устаревшая] Интерактивно запрашивает данные. Используйте 'check' вместо этого.
    """
    print("⚠️  Команда 'run' устарела. Используйте 'check' для лучшего опыта.")
    print("   Пример: python main.py check -s StudentName -l lab-01\n")
    
    # Проверяем наличие токена
    if not token:
        print("❌ Токен не указан!")
        print("   Укажите токен одним из способов:")
        print("   1. Добавьте GITHUB_TOKEN или GITLAB_TOKEN в файл .env")
        print("   2. Экспортируйте переменную: export GITHUB_TOKEN=ваш_токен")
        print("   3. Передайте через --token: --token ваш_токен")
        raise typer.Exit(code=1)

    # --- Интерактивный ввод ---
    try:
        platform_name = "GitLab" if platform.lower() == "gitlab" else "GitHub"
        student_alias = input(f"Введите {platform_name} alias студента (например, Nurassyl28): ").strip()
        repo_name = input(f"Введите имя репозитория (например, lab-01-market-product-and-git): ").strip()

        if not spec_path.exists():
            print(f"❌ Файл спецификации не найден: {spec_path}")
            raise typer.Exit(code=1)

        lab_spec = load_spec(str(spec_path))
        
        # Заменяем имя репозитория из спеки на введенное пользователем
        lab_spec.repo_name = repo_name

        # --- Подготовка ---
        Path(output_dir).mkdir(exist_ok=True)
        # Очищаем старые результаты для этого студента
        student_results_dir = Path(output_dir) / student_alias
        student_results_dir.mkdir(exist_ok=True)
        
        if (student_results_dir / "summary.html").exists():
            (student_results_dir / "summary.html").unlink()
        if (student_results_dir / "results.jsonl").exists():
            (student_results_dir / "results.jsonl").unlink()

        # --- Основная логика проверки ---
        print(f"\n--- 👨‍🎓 Начинаю проверку: {student_alias}/{repo_name} ({platform}) ---")

        # Создаем клиент для нужной платформы
        client = create_client(
            platform=platform,
            token=token,
            repo_owner=student_alias,
            repo_name=lab_spec.repo_name,
            gitlab_url=gitlab_url
        )

        # 1. Проверяем доступность репозитория
        repo_info = client.get_repo_info()
        if not repo_info:
            print(f"  ❌ Не удалось получить информацию о репозитории. Возможные причины:")
            print(f"     - Репозиторий не существует")
            print(f"     - Неверный GitHub токен (ошибка 401)")
            print(f"     - Репозиторий приватный и токен не имеет доступа")
            # Создаем отчет о провале
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Не удалось получить информацию о репозитории. Проверьте токен и доступность репозитория.")
            raise typer.Exit()
        
        if repo_info.get('private'):
            print(f"  ❌ Репозиторий является приватным. Проверка остановлена.")
            # Создаем отчет о провале
            reporter = Reporter(student_alias=student_alias, results=[])
            reporter.write_failure_report(student_results_dir, "Репозиторий является приватным.")
            raise typer.Exit()

        # 2. Скачиваем архив
        reader = RepoReader(
            owner=student_alias, 
            repo_name=lab_spec.repo_name, 
            token=token,
            platform=platform,
            gitlab_url=gitlab_url
        )
        if not reader._zip_file:
             print(f"  ❌ Не удалось скачать zip-архив репозитория. Проверка файловой системы будет невозможна.")
        
        # Получаем branch из спецификации или используем default
        branch = None
        if hasattr(lab_spec, 'discovery') and lab_spec.discovery:
            branch = lab_spec.discovery.get('default_branch')
        
        # 3. Запускаем проверки
        engine = CheckEngine(client, reader, branch=branch)
        results = []
        for check_spec in lab_spec.checks:
            # Используем title, если есть, иначе description, иначе id
            check_description = check_spec.title or check_spec.description or check_spec.id
            print(f"  ▶️  Запуск проверки: {check_description}")
            result = engine.run_check(check_spec.id, check_spec.type, check_spec.params, check_description)
            results.append(result)

        # 4. Анализ с помощью LLM
        llm_analysis = None
        if gemini_api_key:
            try:
                from autochecker.llm_analyzer import analyze_repo
                print("🤖 Запуск анализа с помощью LLM...")
                llm_analysis = analyze_repo(
                    gemini_api_key, 
                    reader, 
                    client, 
                    lab_spec=lab_spec, 
                    repo_owner=student_alias,
                    check_results=results
                )
            except ImportError:
                print("🚨 Не найдены зависимости для LLM-анализа.")
                print("   Пожалуйста, установите их: pip install -r requirements.txt")
                llm_analysis = {
                    "verdict": "анализ_пропущен",
                    "reasons": ["Зависимости для LLM-анализа не установлены. Выполните 'pip install -r requirements.txt'"],
                    "quotes": [],
                }
        else:
            print("⏭️  LLM-анализ пропущен, так как не задан GEMINI_API_KEY.")


        # 5. Сохраняем отчет
        reporter = Reporter(
            student_alias=student_alias, 
            results=results, 
            repo_url=repo_info.get("html_url"),
            llm_analysis=llm_analysis
        )
        reporter.write_jsonl(student_results_dir)
        reporter.write_html(student_results_dir)

        print(f"\n--- ✅ Проверка завершена. Результаты сохранены в: {student_results_dir} ---")

    except KeyboardInterrupt:
        print("\n\nПрограмма прервана пользователем.")
    except typer.Exit:
        # Это нормальный выход, не обрабатываем
        raise
    except Exception as e:
        # Безопасно обрабатываем ошибку с Unicode
        try:
            error_msg = str(e) if str(e) else repr(e)
        except (UnicodeEncodeError, UnicodeDecodeError):
            error_msg = repr(e) if repr(e) else "Unknown error"
        
        if error_msg:
            try:
                print(f"\n❌ Произошла непредвиденная ошибка: {error_msg}")
            except UnicodeEncodeError:
                print(f"\n[ERROR] Unexpected error: {error_msg}")
        else:
            print(f"\n❌ Произошла непредвиденная ошибка (тип: {type(e).__name__})")
        raise typer.Exit(code=1)

@app.command()
def batch(
    students_file: Path = typer.Option(..., "--students", "-s", help="Файл со списком студентов (CSV/JSON/TXT)"),
    lab: str = typer.Option("lab-01", "--lab", "-l", help="Номер лабы: lab-01, lab-02, ..."),
    platform: str = typer.Option("github", "--platform", "-p", help="Платформа: github или gitlab"),
    gitlab_url: str = typer.Option("https://gitlab.astanait.edu.kz", "--gitlab-url", help="URL GitLab сервера"),
    output_dir: str = typer.Option("results", "--output", "-o", help="Папка для результатов"),
    token: str = typer.Option(None, envvar=["GITHUB_TOKEN", "GITLAB_TOKEN"], help="Access Token"),
    gemini_api_key: str = typer.Option(None, envvar="GEMINI_API_KEY", help="Gemini API Key"),
    max_workers: int = typer.Option(2, "--workers", "-w", help="Параллельных потоков (2-3 рекомендуется)"),
    check_plagiarism: bool = typer.Option(True, "--plagiarism/--no-plagiarism", help="Проверка плагиата"),
    plagiarism_threshold: float = typer.Option(0.5, "--threshold", help="Порог плагиата (0.0-1.0). 0.5 = 50% файлов идентичны"),
):
    """
    📋 Массовая проверка студентов (до 300+ студентов).
    
    Примеры:
      python main.py batch -s students.csv -l lab-01 -p github
      python main.py batch -s students.csv -l lab-01 -p gitlab --gitlab-url https://gitlab.astanait.edu.kz
    
    Формат students.csv:
      student_alias
      Nurassyl28
      student2
      ...
    """
    # Проверяем токен
    if not token:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITLAB_TOKEN")
    
    if not token:
        print("❌ Токен не найден! Добавьте GITHUB_TOKEN или GITLAB_TOKEN в .env")
        raise typer.Exit(code=1)
    
    # Получаем конфиг лабы
    lab_config = LAB_CONFIG.get(lab)
    if not lab_config:
        print(f"❌ Лаба '{lab}' не найдена!")
        print(f"   Доступные: {', '.join(LAB_CONFIG.keys())}")
        raise typer.Exit(code=1)
    
    if not lab_config["ready"]:
        print(f"⚠️  {lab_config['name']} ещё не готова!")
        raise typer.Exit(code=1)
    
    repo_name = lab_config["repo_suffix"]
    spec_path = lab_config["spec"]
    
    print("\n" + "="*60)
    print("📋 МАССОВАЯ ПРОВЕРКА")
    print("="*60)
    print(f"  Платформа:  {platform}")
    print(f"  Лаба:       {lab_config['name']}")
    print(f"  Репо:       {repo_name}")
    print(f"  Студенты:   {students_file}")
    print(f"  Плагиат:    {'✅ включен' if check_plagiarism else '❌ выключен'}")
    print(f"  Потоки:     {max_workers}")
    print("="*60 + "\n")
    
    try:
        from autochecker.batch_processor import process_batch
        
        process_batch(
            students_file=str(students_file),
            repo_name=repo_name,
            spec_path=str(spec_path),
            token=token,
            gemini_api_key=gemini_api_key,
            output_dir=output_dir,
            max_workers=max_workers,
            check_plagiarism=check_plagiarism,
            plagiarism_threshold=plagiarism_threshold,
            platform=platform,
            gitlab_url=gitlab_url,
            branch=branch
        )
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@app.command()
def labs():
    """📚 Показать список доступных лабораторных работ."""
    print("\n" + "="*60)
    print("📚 ЛАБОРАТОРНЫЕ РАБОТЫ")
    print("="*60)
    
    for lab_id, config in LAB_CONFIG.items():
        status = "✅ Готова" if config["ready"] else "🚧 В разработке"
        print(f"\n  {lab_id}:")
        print(f"    Название: {config['name']}")
        print(f"    Репо:     {config['repo_suffix']}")
        print(f"    Статус:   {status}")
    
    print("\n" + "="*60)
    print("💡 Использование:")
    print("   python main.py check -s StudentName -l lab-01")
    print("   python main.py batch -s students.csv -l lab-01")
    print("="*60 + "\n")


if __name__ == "__main__":
    app()
