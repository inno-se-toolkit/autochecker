# autochecker/reporter.py
import json
from typing import List, Dict, Optional

class Reporter:
    """Генерирует отчеты о результатах проверок."""
    def __init__(self, student_alias: str, results: List[Dict], repo_url: str = None, llm_analysis: Optional[Dict] = None):
        self._alias = student_alias
        self._results = results
        self._repo_url = repo_url
        self._llm_analysis = llm_analysis

    def _get_summary(self):
        total = len(self._results)
        passed = sum(1 for r in self._results if r['status'] == 'PASS')
        failed = sum(1 for r in self._results if r['status'] == 'FAIL')
        errored = sum(1 for r in self._results if r['status'] == 'ERROR')
        score = (passed / total) * 100 if total > 0 else 0
        
        summary = {
            "student_alias": self._alias,
            "score": f"{score:.2f}%",
            "passed_checks": passed,
            "failed_checks": failed,
            "errored_checks": errored,
            "total_checks": total,
        }
        if self._llm_analysis:
            summary["llm_analysis"] = self._llm_analysis
        return summary

    def write_jsonl(self, output_dir: str):
        """Записывает детальные результаты в .jsonl файл."""
        summary = self._get_summary()
        # Добавляем summary в начало файла
        lines = [json.dumps(summary)]
        for res in self._results:
            lines.append(json.dumps(res))
        
        filepath = f"{output_dir}/results.jsonl"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"📄 Детальный отчет для {self._alias} записан в {filepath}")

    def write_html(self, output_dir: str):
        """Генерирует простой HTML-отчет."""
        summary = self._get_summary()
        
        if self._repo_url:
            title = f"<h1>Отчет для: <a href='{self._repo_url}' target='_blank'>{self._alias}</a> - {summary['score']}</h1>"
        else:
            title = f"<h1>Отчет для: {self._alias} - {summary['score']}</h1>"

        html = title

        if self._llm_analysis:
            html += "<h2>🤖 Анализ от нейросети</h2>"
            html += f"<p><b>Вердикт:</b> {self._llm_analysis.get('verdict', 'нет данных')}</p>"
            
            # Показываем анализ по задачам, если есть
            if self._llm_analysis.get('task_analysis'):
                html += "<h3>Детальный анализ по задачам:</h3>"
                for task in self._llm_analysis['task_analysis']:
                    html += f"<div style='margin-bottom: 20px; border-left: 3px solid #ccc; padding-left: 10px;'>"
                    html += f"<h4>Task {task.get('task_number', '?')}: {task.get('task_name', 'Неизвестная задача')}</h4>"
                    html += f"<p><b>Результат:</b> {task.get('result', 'Не указан')}</p>"
                    html += f"<p><b>Аргументация:</b> {task.get('argumentation', 'Нет аргументации')}</p>"
                    if task.get('quotes'):
                        html += f"<p><b>Цитаты:</b> {task.get('quotes')}</p>"
                    if task.get('link'):
                        html += f"<p><b>Ссылка:</b> <a href='{task.get('link')}' target='_blank'>{task.get('link')}</a></p>"
                    html += "</div>"
            
            if self._llm_analysis.get('reasons'):
                html += "<h3>Общая аргументация:</h3><ul>"
                for reason in self._llm_analysis['reasons']:
                    html += f"<li>{reason}</li>"
                html += "</ul>"
            if self._llm_analysis.get('quotes'):
                html += "<h3>Цитаты из работы:</h3><blockquote>"
                for quote in self._llm_analysis['quotes']:
                    html += f"<p><i>\"{quote}\"</i></p>"
                html += "</blockquote>"


        html += "<h2>⚙️ Результаты автоматических проверок</h2>"
        html += "<ul>"
        html += f"<li>✅ Пройдено: {summary['passed_checks']}</li>"
        html += f"<li>❌ Провалено: {summary['failed_checks']}</li>"
        html += f"<li>⚠️ Ошибок: {summary['errored_checks']}</li>"
        html += "</ul>"
        html += "<h3>Детали:</h3><table border='1'><tr><th>ID</th><th>Статус</th><th>Описание</th><th>Детали</th></tr>"

        for res in self._results:
            status_icon = "✅" if res['status'] == 'PASS' else "❌" if res['status'] == 'FAIL' else "⚠️"
            description = res.get('description', '')
            details = res.get('details', '')
            # Показываем детали только если они есть и статус не PASS
            details_cell = f"<td>{details}</td>" if details else "<td>-</td>"
            html += f"<tr><td>{res['id']}</td><td>{status_icon} {res['status']}</td><td>{description}</td>{details_cell}</tr>"

        html += "</table>"

        filepath = f"{output_dir}/summary.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📈 HTML-отчет для {self._alias} записан в {filepath}")

    def write_failure_report(self, output_dir: str, message: str):
        """Генерирует HTML-отчет о полном провале проверки."""
        html = f"<h1>Отчет для: {self._alias}</h1>"
        html += f"<h2>❌ Проверка провалена</h2>"
        html += f"<p>{message}</p>"

        filepath = f"{output_dir}/summary.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📈 HTML-отчет о провале для {self._alias} записан в {filepath}")
