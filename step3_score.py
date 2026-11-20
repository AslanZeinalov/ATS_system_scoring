"""
ATS-скоринг: детерминированный скор + бонус за проекты + LLM-семантика (5 запросов).
"""

import yaml
import re
import os
from datetime import datetime

from llm_semantic_match import (
    semantic_match_tasks,
    semantic_match_methods,
    gap_analysis,
    tailoring_suggestions,
    rescore_after_tailoring,
)


CANDIDATE_PROFILE = "profile/candidate.yaml"

WEIGHT_TOOLS = 0.3
WEIGHT_METHODS = 0.2
WEIGHT_TASKS = 0.5
BONUS_CONFIRMED = 1.3


def log(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", flush=True)


def normalize_text(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\sа-яё]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_candidate_profile(filepath: str) -> dict:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Профиль не найден: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    skills_base = {normalize_text(s["name"]) for s in profile.get("skills", [])}
    tasks_base = {normalize_text(t) for t in profile.get("tasks", [])}

    skills_confirmed, tasks_confirmed = set(), set()
    for p in profile.get("projects", []):
        for s in p.get("skills_used", []):
            skills_confirmed.add(normalize_text(s))
        for t in p.get("tasks_done", []):
            tasks_confirmed.add(normalize_text(t))

    # Методы сравниваем с объединением skills + tasks профиля
    profile_methods = skills_base | tasks_base

    return {
        "raw": profile,
        "skills_base": skills_base,
        "skills_confirmed": skills_confirmed,
        "tasks_base": tasks_base,
        "tasks_confirmed": tasks_confirmed,
        "profile_methods": profile_methods,
    }


def score_category(required_items, base_set, confirmed_set, weight):
    required_count = len(required_items)
    if required_count == 0:
        return {"score": 0.0, "required_count": 0, "weight": weight,
                "matched_confirmed": [], "matched_base": [], "missing": []}

    matched_confirmed, matched_base, missing = [], [], []
    for req in required_items:
        rn = normalize_text(req)
        if rn in base_set:
            (matched_confirmed if rn in confirmed_set else matched_base).append(req)
            continue
        partial = any((rn in c or c in rn) for c in base_set if len(c) > 3 and len(rn) > 3)
        if partial:
            p_conf = any((rn in c or c in rn) for c in confirmed_set if len(c) > 3 and len(rn) > 3)
            (matched_confirmed if p_conf else matched_base).append(f"{req} (частично)")
        else:
            missing.append(req)

    base = (len(matched_confirmed) + len(matched_base)) / required_count * 100
    bonus = len(matched_confirmed) / required_count * 100 * (BONUS_CONFIRMED - 1.0)
    return {"score": round(min(base + bonus, 100.0), 1), "required_count": required_count,
            "weight": weight, "matched_confirmed": matched_confirmed,
            "matched_base": matched_base, "missing": missing}


def _recompute_total(breakdown):
    active = [c for c in breakdown.values() if c["required_count"] > 0]
    if not active:
        return 0.0
    wsum = sum(c["weight"] for c in active)
    return round(sum(c["score"] * c["weight"] for c in active) / wsum, 1)


def _rescore_tasks(data):
    rc = data["required_count"]
    if rc == 0:
        return
    base = (len(data["matched_confirmed"]) + len(data["matched_base"])) / rc * 100
    bonus = len(data["matched_confirmed"]) / rc * 100 * (BONUS_CONFIRMED - 1.0)
    data["score"] = round(min(base + bonus, 100.0), 1)


def calculate_match_score_full(vacancy_requirements, candidate, use_llm=True):
    breakdown = {
        "tools": score_category(vacancy_requirements.get("tools", []),
                                candidate["skills_base"], candidate["skills_confirmed"], WEIGHT_TOOLS),
        "methods": score_category(vacancy_requirements.get("methods", []),
                                  candidate["skills_base"], candidate["skills_confirmed"], WEIGHT_METHODS),
        "tasks": score_category(vacancy_requirements.get("tasks", []),
                                candidate["tasks_base"], candidate["tasks_confirmed"], WEIGHT_TASKS),
    }
    total = _recompute_total(breakdown)
    result = {"total_score": total, "breakdown": breakdown,
              "gap_analysis": [], "llm_suggestions": {}, "rescored_score": total}

    if not use_llm or total == 0:
        return result

    # Запрос #1: семантика задач
    if breakdown["tasks"]["missing"]:
        pm = candidate["raw"].get("tasks", [])
        m = semantic_match_tasks(breakdown["tasks"]["missing"], pm)
        still = []
        for t in breakdown["tasks"]["missing"]:
            if m.get(t):
                (breakdown["tasks"]["matched_confirmed"] if normalize_text(m[t]) in candidate["tasks_confirmed"]
                 else breakdown["tasks"]["matched_base"]).append(f"{t} → {m[t]}")
            else:
                still.append(t)
        breakdown["tasks"]["missing"] = still
        _rescore_tasks(breakdown["tasks"])

    # Запрос #2: семантика методов
    if breakdown["methods"]["missing"]:
        mm = semantic_match_methods(breakdown["methods"]["missing"], list(candidate["profile_methods"]))
        still = []
        for t in breakdown["methods"]["missing"]:
            if mm.get(t):
                breakdown["methods"]["matched_base"].append(f"{t} → {mm[t]}")
            else:
                still.append(t)
        breakdown["methods"]["missing"] = still
        _rescore_methods(breakdown["methods"])

    result["total_score"] = _recompute_total(breakdown)

    # Запросы #3-#5: gap, tailoring, rescore
    result["gap_analysis"] = gap_analysis(vacancy_requirements, candidate["raw"])
    result["llm_suggestions"] = tailoring_suggestions(vacancy_requirements, candidate["raw"])
    result["rescored_score"] = rescore_after_tailoring(vacancy_requirements, candidate["raw"])
    return result


def _rescore_methods(data):
    rc = data["required_count"]
    if rc == 0:
        return
    base = (len(data["matched_confirmed"]) + len(data["matched_base"])) / rc * 100
    bonus = len(data["matched_confirmed"]) / rc * 100 * (BONUS_CONFIRMED - 1.0)
    data["score"] = round(min(base + bonus, 100.0), 1)