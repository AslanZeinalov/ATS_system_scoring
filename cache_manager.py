"""
Менеджер кэша обработанных вакансий.
Сохраняет результаты анализа, чтобы не обрабатывать их повторно.
"""

import os
import json
from datetime import datetime

CACHE_FILE = "cache/analyzed_vacancies.json"


def load_analyzed_vacancies() -> dict:
    """Загружает кэш обработанных вакансий. Возвращает dict: vacancy_id -> данные."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_analyzed_vacancies(analyzed: dict) -> None:
    """Сохраняет кэш обработанных вакансий."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=2)


def is_vacancy_analyzed(vacancy_id: str, analyzed: dict) -> bool:
    """Проверяет, была ли вакансия уже проанализирована с LLM."""
    if vacancy_id not in analyzed:
        return False
    data = analyzed[vacancy_id]
    # Считаем проанализированной, если есть deep_score (результат LLM-анализа)
    return "deep_score" in data


def get_analyzed_vacancy(vacancy_id: str, analyzed: dict) -> dict:
    """Возвращает данные уже проанализированной вакансии."""
    return analyzed.get(vacancy_id, {})


def update_analyzed_vacancy(vacancy_id: str, vacancy_data: dict, analyzed: dict) -> None:
    """Обновляет данные вакансии в кэше."""
    analyzed[vacancy_id] = vacancy_data
    save_analyzed_vacancies(analyzed)


def get_unanalyzed_vacancies(vacancies: list, analyzed: dict) -> list:
    """Возвращает список вакансий, которые ещё не были проанализированы."""
    return [v for v in vacancies if not is_vacancy_analyzed(v["vacancy_id"], analyzed)]


def clear_cache() -> None:
    """Очищает кэш обработанных вакансий."""
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        print("Кэш обработанных вакансий очищен.")