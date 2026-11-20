"""
Главный оркестратор ATS-системы.
1. Собирает свежие вакансии (переиспользует этапы 1-2).
2. Извлекает требования (переиспользует этап 4).
3. Быстрый скоринг всех вакансий (0 LLM-запросов).
4. Глубокий LLM-анализ только для ТОП-10 (до 50 запросов).
5. Генерация Excel и Markdown отчетов.
"""

import os
import json
import pandas as pd
from datetime import datetime

import config
from step3_score import load_candidate_profile, calculate_match_score_full
from stage1_collect_links import collect_links, save_and_filter
from stage2_parse_vacancies import run_parser as run_stage2
from stage4_extract_requirements import extract_dictionary, DICTIONARY
from cache_manager import (
    load_analyzed_vacancies,
    save_analyzed_vacancies,
    is_vacancy_analyzed,
    get_analyzed_vacancy,
    update_analyzed_vacancy,
    get_unanalyzed_vacancies,
)
import sys

FORCE_REANALYZE = "--force" in sys.argv

def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def ensure_dirs():
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs("cache/llm_cache", exist_ok=True)
    os.makedirs("weights", exist_ok=True)


def fetch_and_extract_vacancies() -> list:
    """
    Собирает и парсит вакансии. 
    Читает все спарсенные данные (без жесткого фильтра по названию),
    так как ATS-скоринг сам отберет только релевантные.
    """
    log("Запуск сбора ссылок (Этап 1)...")
    # Временно ограничиваем страницы для быстрого теста. 
    # Для полного прогона убери следующую строку или поставь config.MAX_PAGES = 50
    import stage1_collect_links
    original_max_pages = stage1_collect_links.config.MAX_PAGES
    stage1_collect_links.config.MAX_PAGES = 3  # Быстрый сбор ~60-90 вакансий
    
    items = collect_links()
    if not items:
        log("Не удалось собрать ссылки. Проверь VPN и настройки config.py", level="ERROR")
        return []
    
    save_and_filter(items)
    stage1_collect_links.config.MAX_PAGES = original_max_pages

    log("Запуск парсинга карточек (Этап 2)...")
    run_stage2()

    # ИЗМЕНЕНИЕ: Читаем все спарсенные вакансии (файл после дедупликации)
    # ATS-скоринг сам отберет только релевантные по навыкам и задачам.
    input_file = config.DEDUP_FILE if os.path.exists(config.DEDUP_FILE) else config.RAW_FILE
    
    if not os.path.exists(input_file):
        log("Файл с вакансиями не создан. Остановка.", level="ERROR")
        return []

    log(f"Чтение спарсенных вакансий из {input_file}...")
    df = pd.read_csv(input_file, dtype=str).fillna("")
    
    vacancies = []
    for _, row in df.iterrows():
        # Пропускаем вакансии без описания (они бесполезны для анализа)
        desc = row.get("description", "")
        if not desc or len(desc) < 50:
            continue
            
        # Используем словарь из stage4 для быстрого извлечения требований без LLM
        text_to_analyze = f"{row.get('key_skills', '')} {desc}"
        extracted = extract_dictionary(text_to_analyze)
        
        req_tools = [item[1] for item in extracted if item[0] == "tool"]
        req_methods = [item[1] for item in extracted if item[0] == "method"]
        req_tasks = [item[1] for item in extracted if item[0] == "task"]
        
        # Сырой текст задач для LLM-семантики (берем из описания)
        raw_tasks_text = desc

        vacancies.append({
            "vacancy_id": row["vacancy_id"],
            "title": row.get("title", "Без названия"),
            "company": row.get("company", "Не указана"),
            "url": row["url"],
            "requirements": {
                "tools": req_tools,
                "methods": req_methods,
                "tasks": req_tasks,
                "raw_tasks_text": raw_tasks_text[:2000]  # Обрезаем для экономии токенов
            }
        })
    
    log(f"Успешно собрано и обработано {len(vacancies)} вакансий (пропущены пустые).")
    return vacancies


def run_fast_scoring(vacancies: list, candidate: dict) -> list:
    log("Запуск быстрого скоринга всех вакансий...")
    scored_vacancies = []
    skipped = 0
    for v in vacancies:
        req = v["requirements"]
        total_req = len(req["tools"]) + len(req["methods"]) + len(req["tasks"])
        if total_req == 0:  # из вакансии ничего не извлечено — бесполезна для ATS
            skipped += 1
            continue
        score_data = calculate_match_score_full(req, candidate, use_llm=False)
        v["score"] = score_data["total_score"]
        v["breakdown"] = score_data["breakdown"]
        v["total_req"] = total_req
        scored_vacancies.append(v)

    filtered = [v for v in scored_vacancies if v["score"] >= config.MIN_SCORE_THRESHOLD]
    filtered.sort(key=lambda x: x["score"], reverse=True)
    log(f"Пропущено вакансий без требований: {skipped}. "
        f"Найдено {len(filtered)} выше порога {config.MIN_SCORE_THRESHOLD}%.")
    return filtered


def run_deep_analysis(top_vacancies: list, candidate: dict) -> list:
    """Глубокий LLM-анализ для ТОП-N вакансий с проверкой кэша."""
    log(f"Запуск глубокого LLM-анализа для ТОП-{len(top_vacancies)} вакансий...")

    if FORCE_REANALYZE:
        log("Флаг --force: очищаем кэш и анализируем все вакансии заново", level="WARNING")
        from cache_manager import clear_cache
        clear_cache()
        analyzed_cache = {}
    else:
        # Загружаем кэш уже обработанных вакансий
        analyzed_cache = load_analyzed_vacancies()
    
    log(f"В кэше найдено {len(analyzed_cache)} ранее обработанных вакансий")
    
    # Разделяем вакансии на новые и уже обработанные
    new_vacancies = get_unanalyzed_vacancies(top_vacancies, analyzed_cache)
    cached_vacancies = [v for v in top_vacancies if is_vacancy_analyzed(v["vacancy_id"], analyzed_cache)]
    
    log(f"Новых вакансий для анализа: {len(new_vacancies)}")
    log(f"Уже обработанных (из кэша): {len(cached_vacancies)}")
    
    # Восстанавливаем данные из кэша для уже обработанных
    for v in cached_vacancies:
        cached_data = get_analyzed_vacancy(v["vacancy_id"], analyzed_cache)
        v["deep_score"] = deep_score["total_score"]
        v["deep_breakdown"] = deep_score["breakdown"]
        v["llm_suggestions"] = deep_score.get("llm_suggestions", {})
        v["gap_analysis"] = deep_score.get("gap_analysis", [])
        v["rescored_score"] = deep_score.get("rescored_score", deep_score["total_score"])
        log(f"  ✓ Вакансия {v['vacancy_id']} восстановлена из кэша (скор: {v['deep_score']}%)")
    
    # Обрабатываем только новые вакансии
    for i, v in enumerate(new_vacancies, 1):
        log(f"Обработка новой вакансии {i}/{len(new_vacancies)}: {v['title']}")
        
        # Добавляем сырые задачи из описания в требования для LLM-семантики
        if v["requirements"].get("raw_tasks_text"):
            import re
            raw_tasks_list = [t.strip() for t in re.split(r'[.!?;]', v["requirements"]["raw_tasks_text"]) if 10 < len(t.strip()) < 100]
            v["requirements"]["tasks"].extend(raw_tasks_list)
            v["requirements"]["tasks"] = list(dict.fromkeys(v["requirements"]["tasks"]))

        # Полный скоринг с LLM
        deep_score = calculate_match_score_full(v["requirements"], candidate, use_llm=True)
        
        v["deep_score"] = deep_score["total_score"]
        v["deep_breakdown"] = deep_score["breakdown"]
        v["llm_suggestions"] = deep_score.get("llm_suggestions", {})
        v["gap_analysis"] = deep_score.get("gap_analysis", [])
        
        # Сохраняем в кэш
        update_analyzed_vacancy(v["vacancy_id"], v, analyzed_cache)
        log(f"  ✓ Вакансия {v['vacancy_id']} проанализирована и сохранена в кэш (скор: {v['deep_score']}%)")
    
    # Объединяем и сортируем по deep_score
    all_analyzed = cached_vacancies + new_vacancies
    all_analyzed.sort(key=lambda x: x.get("deep_score", x["score"]), reverse=True)
    
    return all_analyzed


def generate_reports(top_vacancies: list, candidate: dict):
    log("Генерация отчетов...")
    excel_data = []
    for v in top_vacancies:
        bd = v.get("deep_breakdown", v.get("breakdown", {}))
        tools = bd.get("tools", {}); methods = bd.get("methods", {}); tasks = bd.get("tasks", {})
        matched_tools = tools.get("matched_confirmed", []) + tools.get("matched_base", [])
        missing_all = (tools.get("missing", []) + methods.get("missing", []) + tasks.get("missing", []))
        tail = v.get("llm_suggestions", {}).get("tailoring", {})
        tail_str = "; ".join(f"{k}: {val}" for k, val in list(tail.items())[:3]) if tail else "Нет данных"
        gap_str = "; ".join(v.get("gap_analysis", [])[:3]) if v.get("gap_analysis") else "Критических пробелов нет"
        excel_data.append({
            "Компания": v["company"], "Вакансия": v["title"], "Ссылка": v["url"],
            "Базовый скор (%)": v["score"],
            "Скор после LLM (%)": v.get("deep_score", v["score"]),
            "Скор после tailoring (%)": v.get("rescored_score", v.get("deep_score", v["score"])),
            "Δ (tailoring)": round(v.get("rescored_score", 0) - v["score"], 1),
            "Совпавшие инструменты": ", ".join(matched_tools),
            "Отсутствующие навыки": ", ".join(missing_all),
            "Gap-анализ": gap_str,
            "Рекомендации LLM (tailoring)": tail_str[:300],
        })

    df_excel = pd.DataFrame(excel_data)
    excel_path = os.path.join(config.OUTPUT_DIR, "ats_report_detailed.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_excel.to_excel(writer, sheet_name="Top_Vacancies", index=False)

        # Берём вакансию с МАКСИМАЛЬНЫМ числом требований (чтобы лист не был пустым)
        if top_vacancies:
            best = max(top_vacancies, key=lambda x: x.get("total_req", 0))
            bd = best.get("deep_breakdown", best.get("breakdown", {}))
            rows = []
            for cat in ["tools", "methods", "tasks"]:
                d = bd.get(cat, {})
                rows.append({
                    "Категория": {"tools": "Инструменты", "methods": "Методы", "tasks": "Задачи"}[cat],
                    "Совпало (подтверждено)": ", ".join(d.get("matched_confirmed", [])),
                    "Совпало (база)": ", ".join(d.get("matched_base", [])),
                    "Отсутствует": ", ".join(d.get("missing", [])),
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="Example_Breakdown", index=False)
    log(f"Excel отчет сохранен: {excel_path}")

    # Markdown
    md = ["# ATS-Отчет: Анализ релевантности вакансий",
          f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
          f"Кандидат: {candidate['raw']['personal']['name']}",
          f"Проанализировано в топе: {len(top_vacancies)}\n"]
    for i, v in enumerate(top_vacancies, 1):
        bd = v.get("deep_breakdown", v.get("breakdown", {}))
        md.append(f"## {i}. {v['title']} @ {v['company']}")
        md.append(f"**Скор:** {v['score']}% → LLM {v.get('deep_score', v['score'])}% → "
                  f"tailoring {v.get('rescored_score', v.get('deep_score', v['score']))}% | [Ссылка]({v['url']})\n")
        if bd.get("tasks", {}).get("matched_confirmed"):
            md.append("- **Задачи (подтверждено):** " + ", ".join(bd["tasks"]["matched_confirmed"]))
        if v.get("gap_analysis"):
            md.append("- **Зоны роста:** " + "; ".join(v["gap_analysis"][:3]))
        tail = v.get("llm_suggestions", {}).get("tailoring", {})
        if tail:
            md.append("- **Tailoring:** " + "; ".join(f"{k}: {val}" for k, val in list(tail.items())[:2]))
        md.append("\n---\n")
    md_path = os.path.join(config.OUTPUT_DIR, "ats_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    log(f"Markdown отчет сохранен: {md_path}")


def main():
    log("=" * 60)
    log("ЗАПУСК ATS-ПАЙПЛАЙНА")
    log("=" * 60)
    
    ensure_dirs()
    
    # Загрузка профиля
    candidate = load_candidate_profile(config.CANDIDATE_PROFILE)
    log("Профиль кандидата успешно загружен.")
    
    # 1. Сбор и парсинг
    vacancies = fetch_and_extract_vacancies()
    if not vacancies:
        log("Пайплайн остановлен: нет вакансий для анализа.", level="ERROR")
        return
        
    # 2. Быстрый скоринг
    scored = run_fast_scoring(vacancies, candidate)
    
    # 3. Выбор ТОП-N для глубокого анализа
    top_n = min(config.TOP_N_VACANCIES, len(scored))
    top_vacancies = scored[:top_n]
    
    if not top_vacancies:
        log("Ни одна вакансия не преодолела порог релевантности.", level="WARNING")
        return
        
    # 4. Глубокий LLM-анализ
    analyzed = run_deep_analysis(top_vacancies, candidate)
    
    # 5. Генерация отчетов
    generate_reports(analyzed, candidate)
    
    log("=" * 60)
    log("ПАЙПЛАЙН ЗАВЕРШЕН УСПЕШНО")
    log(f"Проверь папку {config.OUTPUT_DIR} для просмотра результатов.")
    log("=" * 60)


if __name__ == "__main__":
    main()