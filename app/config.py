# app/config.py
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
# FAVORITES_FILE = DATA_DIR / "favorites_shares.json"
# новый файл избранного (чтобы не конфликтовать со старым форматом)
FAVORITES_FILE = DATA_DIR / "favorites_instruments.json"
CANDLES_DIR = DATA_DIR / "candles_cache"

# Database
DB_DIR = APP_DIR / "db"
DB_FILE = DATA_DIR / "tbpr.db"

SECRETS_DIR = APP_DIR / "secrets"
TOKEN_FILE = SECRETS_DIR / "tinvest_token.txt"
TOKEN_ERROR = ""

# Реальный счёт
REAL_TOKEN_FILE = SECRETS_DIR / "tinvest_real_token.txt"
REAL_TOKEN_ERROR = ""


def _read_token_from_file(path: Path) -> str:
    if not path.exists():
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text("paste_your_t_invest_token_here\n", encoding="utf-8")
        raise FileNotFoundError(
            "Token file was created automatically: "
            f"{path}. Open it and replace placeholder with your real token."
        )

    token = path.read_text(encoding="utf-8").strip()
    if not token or token == "paste_your_t_invest_token_here":
        raise ValueError(f"Token file is empty: {path}")
    return token


try:
    TOKEN = _read_token_from_file(TOKEN_FILE)
except Exception as exc:
    TOKEN = ""
    TOKEN_ERROR = str(exc)

try:
    REAL_TOKEN = _read_token_from_file(REAL_TOKEN_FILE)
except Exception as exc:
    REAL_TOKEN = ""
    REAL_TOKEN_ERROR = str(exc)
