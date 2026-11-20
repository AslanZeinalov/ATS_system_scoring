"""
LLM-модуль для ATS-скоринга.
Поддерживает Yandex Cloud и OpenRouter. Переключается через config.LLM_PROVIDER.
"""

import os
import re
import json
import hashlib
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

import config


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def normalize_text(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\sа-яё]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ============================================================
# КЭШ
# ============================================================

CACHE_FILES = {
    "tasks": "tasks_semantic.json",
    "methods": "methods_semantic.json",
    "gap": "gap_analysis.json",
    "tailoring": "tailoring_suggestions.json",
    "rescore": "rescore.json",
}


def load_cache(cache_type: str) -> dict:
    filename = os.path.join(config.LLM_CACHE_DIR, CACHE_FILES[cache_type])
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache_type: str, cache: dict) -> None:
    os.makedirs(config.LLM_CACHE_DIR, exist_ok=True)
    filename = os.path.join(config.LLM_CACHE_DIR, CACHE_FILES[cache_type])
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def cache_key(cache_type: str, **kwargs) -> str:
    # Включаем провайдер в ключ, чтобы кэши Yandex и OpenRouter не конфликтовали
    raw = json.dumps({
        "provider": config.LLM_PROVIDER,
        "type": cache_type,
        **kwargs,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# YANDEX CLOUD
# ============================================================


import time  # добавь в начало файла, рядом с другими импортами


def call_yandex(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv(config.YC_API_KEY_ENV, "").strip()
    folder_id = str(config.YC_FOLDER_ID).strip()
    model_name = str(config.YC_MODEL_URI).strip()
    url = str(config.YC_COMPLETION_URL).strip()  # <-- strip() убирает невидимые пробелы/переносы

    full_model_uri = f"gpt://{folder_id}/{model_name}"

    # ПОЛНАЯ ДИАГНОСТИКА ПЕРЕД ОТПРАВКОЙ
    log("=" * 50)
    log(f"URL: [{url}]")
    log(f"modelUri: [{full_model_uri}]")
    log(f"folder_id длина: {len(folder_id)}, api_key длина: {len(api_key)}")
    log("=" * 50)

    if not api_key:
        log(f"Yandex Cloud отключен: не задана {config.YC_API_KEY_ENV}", level="WARNING")
        return ""
    if not folder_id or folder_id == "b1g...":
        log("Yandex Cloud отключен: не задан корректный YC_FOLDER_ID", level="WARNING")
        return ""
    if requests is None:
        return ""

    payload = {
        "modelUri": full_model_uri,
        "completionOptions": {
            "stream": False,
            "temperature": 0.0,
            "maxTokens": "3000",
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": user_prompt},
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id,
    }

    for attempt in range(1, config.LLM_MAX_RETRIES + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=config.LLM_TIMEOUT)
        except Exception as e:
            log(f"Yandex сетевая ошибка ({attempt}): {e}", level="WARNING")
            time.sleep(3 * attempt)
            continue

        if response.status_code == 200:
            try:
                data = response.json()
                return data["result"]["alternatives"][0]["message"]["text"]
            except Exception as e:
                log(f"Yandex не вернула ожидаемый ответ: {e}", level="WARNING")
                return ""

        if response.status_code in (429, 500, 502, 503, 504):
            log(f"Yandex HTTP {response.status_code}, повтор ({attempt})", level="WARNING")
            time.sleep(5 * attempt)
            continue

        log(f"Yandex ошибка {response.status_code}: {response.text}", level="WARNING")
        return ""

    return ""

# ============================================================
# OPENROUTER
# ============================================================

def call_openrouter(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv(config.OPENROUTER_API_KEY_ENV, "").strip()
    if not api_key:
        log(f"OpenRouter отключен: не задана {config.OPENROUTER_API_KEY_ENV}", level="WARNING")
        return ""
    if requests is None:
        return ""

    payload = {
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 3000,
        "reasoning": {"enabled": False},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "hh-ats-scoring",
    }

    for attempt in range(1, config.LLM_MAX_RETRIES + 1):
        try:
            response = requests.post(
                config.OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
                timeout=config.LLM_TIMEOUT,
            )
        except Exception as e:
            log(f"OpenRouter сетевая ошибка ({attempt}): {e}", level="WARNING")
            import time
            time.sleep(3 * attempt)
            continue

        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                log(f"OpenRouter не вернула ожидаемый ответ: {e}", level="WARNING")
                return ""

        if response.status_code in (429, 500, 502, 503, 504):
            log(f"OpenRouter HTTP {response.status_code}, повтор ({attempt})", level="WARNING")
            import time
            time.sleep(5 * attempt)
            continue

        log(f"OpenRouter ошибка {response.status_code}: {response.text[:300]}", level="WARNING")
        return ""

    return ""


# ============================================================
# ЕДИНЫЙ ИНТЕРФЕЙС
# ============================================================

def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Вызывает LLM через активного провайдера из config.LLM_PROVIDER."""
    provider = config.LLM_PROVIDER.lower()
    if provider == "yandex":
        log(f"Провайдер: Yandex Cloud ({config.YC_MODEL_URI})")
        return call_yandex(system_prompt, user_prompt)
    elif provider == "openrouter":
        log(f"Провайдер: OpenRouter ({config.OPENROUTER_MODEL})")
        return call_openrouter(system_prompt, user_prompt)
    else:
        log(f"Неизвестный провайдер: {provider}. Используй 'yandex' или 'openrouter'.", level="ERROR")
        return ""


# ============================================================
# 5 ТИПОВ ЗАПРОСОВ
# ============================================================

def semantic_match_tasks(vacancy_tasks: list, profile_tasks: list) -> dict:
    if not vacancy_tasks or not profile_tasks:
        return {}

    key = cache_key("tasks", v=vacancy_tasks, p=profile_tasks)
    cache = load_cache("tasks")

    if key in cache:
        log("Семантика задач: из кэша")
        return cache[key]

    log(f"Запрос #1: Семантика задач ({len(vacancy_tasks)} задач)")

    system = "Ты помогаешь сопоставлять задачи из вакансий с опытом кандидата. Возвращай строго JSON."
    user = (
        f"Задачи из вакансии:\n"
        + "\n".join(f"- {t}" for t in vacancy_tasks)
        + f"\n\nЗадачи из профиля кандидата:\n"
        + "\n".join(f"- {t}" for t in profile_tasks)
        + f'\n\nВерни JSON: {{"matches": {{"задача_вакансии": "задача_профиля"}}}}\n'
        "Если совпадения нет — null."
    )

    response = call_llm(system, user)
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            result = data.get("matches", {})
            cache[key] = result
            save_cache("tasks", cache)
            return result
        except Exception:
            pass

    return {}


def semantic_match_methods(vacancy_methods: list, profile_methods: list) -> dict:
    if not vacancy_methods or not profile_methods:
        return {}

    key = cache_key("methods", v=vacancy_methods, p=profile_methods)
    cache = load_cache("methods")

    if key in cache:
        log("Семантика методов: из кэша")
        return cache[key]

    log(f"Запрос #2: Семантика методов ({len(vacancy_methods)} методов)")

    system = "Ты сопоставляешь методы анализа из вакансий с навыками кандидата. Возвращай строго JSON."
    user = (
        f"Методы из вакансии:\n"
        + "\n".join(f"- {t}" for t in vacancy_methods)
        + f"\n\nМетоды и навыки кандидата:\n"
        + "\n".join(f"- {t}" for t in profile_methods)
        + f'\n\nВерни JSON: {{"matches": {{"метод_вакансии": "метод_кандидата"}}}}\n'
        "Если совпадения нет — null."
    )

    response = call_llm(system, user)
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            result = data.get("matches", {})
            cache[key] = result
            save_cache("methods", cache)
            return result
        except Exception:
            pass

    return {}


def gap_analysis(vacancy_requirements: dict, profile: dict) -> list:
    key = cache_key("gap", v=vacancy_requirements, p=profile)
    cache = load_cache("gap")

    if key in cache:
        log("Gap-анализ: из кэша")
        return cache[key]

    log("Запрос #3: Gap-анализ")

    system = "Ты анализируешь разрыв между требованиями вакансии и профилем кандидата."
    user = (
        f"Требования вакансии:\n{json.dumps(vacancy_requirements, ensure_ascii=False, indent=2)}\n\n"
        f"Профиль кандидата:\n{json.dumps(profile, ensure_ascii=False, indent=2)[:2000]}\n\n"
        "Найди критические пробелы (навыки или задачи, которых нет у кандидата, но важны для вакансии).\n"
        f'Верни JSON: {{"gaps": ["пробел 1", "пробел 2"]}}'
    )

    response = call_llm(system, user)
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            result = data.get("gaps", [])
            cache[key] = result
            save_cache("gap", cache)
            return result
        except Exception:
            pass

    return []


def tailoring_suggestions(vacancy_requirements: dict, profile: dict) -> dict:
    key = cache_key("tailoring", v=vacancy_requirements, p=profile)
    cache = load_cache("tailoring")

    if key in cache:
        log("Tailoring: из кэша")
        return cache[key]

    log("Запрос #4: Tailoring suggestions")

    system = "Ты помогаешь оптимизировать резюме под конкретную вакансию, не выдумывая опыт."
    user = (
        f"Требования вакансии:\n{json.dumps(vacancy_requirements, ensure_ascii=False, indent=2)}\n\n"
        f"Текущий профиль кандидата:\n{json.dumps(profile, ensure_ascii=False, indent=2)[:2000]}\n\n"
        "Предложи оптимизированные формулировки для резюме, чтобы повысить релевантность.\n"
        "Используй только реальный опыт кандидата, не выдумывай.\n"
        f'Верни JSON: {{"suggestions": {{"section": "новая формулировка"}}}}'
    )

    response = call_llm(system, user)
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            result = data.get("suggestions", {})
            cache[key] = result
            save_cache("tailoring", cache)
            return result
        except Exception:
            pass

    return {}


def rescore_after_tailoring(vacancy_requirements: dict, tailored_profile: dict) -> float:
    key = cache_key("rescore", v=vacancy_requirements, p=tailored_profile)
    cache = load_cache("rescore")

    if key in cache:
        log("Rescore: из кэша")
        return cache[key]

    log("Запрос #5: Rescore после tailoring")

    system = "Ты оцениваешь релевантность профиля кандидата требованиям вакансии."
    user = (
        f"Требования вакансии:\n{json.dumps(vacancy_requirements, ensure_ascii=False, indent=2)}\n\n"
        f"Оптимизированный профиль кандидата:\n{json.dumps(tailored_profile, ensure_ascii=False, indent=2)[:2000]}\n\n"
        "Оцени релевантность от 0 до 100.\n"
        f'Верни JSON: {{"score": число}}'
    )

    response = call_llm(system, user)
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            result = data.get("score", 0)
            cache[key] = result
            save_cache("rescore", cache)
            return result
        except Exception:
            pass

    return 0