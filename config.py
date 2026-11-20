"""
Настройки ATS-системы.
Переключатель провайдера LLM: 'yandex' или 'openrouter'.
"""

# ============================================================
# ПАРСИНГ ВАКАНСИЙ
# ============================================================

SEARCH_QUERIES = [
    "Аналитик данных",
    "Продуктовый аналитик",
    "Data Analyst",
    "Product Analyst",
]

AREA_IDS = []
EXPERIENCE = ["noExperience", "between1And3"]
SCHEDULE = []
PERIOD_DAYS = 1

SEARCH_FIELD = "name"
NO_MAGIC = True
APPLY_TITLE_FILTER = False

MAX_PAGES = 3
DELAY_STAGE1 = 3
DELAY_STAGE2 = 2.5
PAGE_TIMEOUT = 30000
MAX_RETRIES = 2
CHECKPOINT_EVERY = 25
TEST_LIMIT = None

# Дополнительные фильтры (нужны старому коду парсера)
SALARY_FROM = None
CURRENCY = "RUR"
ONLY_WITH_SALARY = False
EMPLOYMENT = []
ORDER_BY = "relevance"

# ============================================================
# ФАЙЛЫ ПАРСЕРА
# ============================================================

LINKS_ALL_FILE = "vacancy_links_all.csv"
LINKS_FILE = "vacancy_links.csv"
LINKS_REVIEW_FILE = "vacancy_links_review.csv"
LINKS_EXCLUDED_FILE = "vacancy_links_excluded.csv"

RAW_FILE = "vacancies_raw.csv"
DEDUP_FILE = "vacancies_dedup.csv"
RELEVANT_FILE = "vacancies_relevant.csv"
EXCLUDED_FILE = "vacancies_excluded.csv"
REVIEW_FILE = "vacancies_review.csv"
FAILED_FILE = "failed_links.csv"

# ============================================================
# ATS-СКОРИНГ
# ============================================================

TOP_N_VACANCIES = 20
MIN_SCORE_THRESHOLD = 40

CANDIDATE_PROFILE = "profile/candidate.yaml"
MARKET_WEIGHTS_FILE = "weights/market_weights.json"

OUTPUT_DIR = "output"
OUTPUT_EXCEL = "output/ats_report_detailed.xlsx"
OUTPUT_PDF_SUMMARY = "output/ats_summary.pdf"

# ============================================================
# LLM ПРОВАЙДЕР (yandex или openrouter)
# ============================================================

LLM_PROVIDER = "yandex"  # <-- переключатель

# --- Yandex Cloud ---
# --- Yandex Cloud ---
YC_API_KEY_ENV = "YC_API_KEY"
YC_FOLDER_ID = "b1gg02gedb4jdqmp8ti4"
YC_MODEL_URI = "yandexgpt/latest"
YC_COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


# --- OpenRouter ---
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "inclusionai/ling-3.2-flash:free"

# --- Общие ---
LLM_TIMEOUT = 90
LLM_MAX_RETRIES = 2
LLM_CACHE_DIR = "cache/llm_cache"