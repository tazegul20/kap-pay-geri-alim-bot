import os
import json
import time
import requests
from requests.auth import HTTPBasicAuth
from typing import Any, Dict, List, Optional, Tuple

BASE_URL = "https://apigwdev.mkk.com.tr/api/vyk"

API_KEY = os.getenv("KAP_API_KEY")
API_SECRET = os.getenv("KAP_API_SECRET")
AUTH = HTTPBasicAuth(API_KEY, API_SECRET)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

# Opsiyonel:
# - KAP_LOOKBACK: ilk kurulumda/kaçırmamak için geriye doğru taranacak index penceresi
# - KAP_SLEEP: API'yi yormamak için istekler arası ufak bekleme (saniye)
# - DEBUG: 1 ise log basar
LOOKBACK = int(os.getenv("KAP_LOOKBACK", "5000"))
SLEEP = float(os.getenv("KAP_SLEEP", "0.2"))
DEBUG = os.getenv("DEBUG", "0") == "1"

STATE_FILE = "state.json"

KEYWORDS = [
    "geri al", "geri alım", "geri alin", "geri alim",
    "pay geri al", "pay geri alım", "pay geri alim", "pay geri alin",
    "geri alınan pay", "geri alinan pay",
    "payların geri alımı", "paylarin geri alimi",
    "share buyback", "buyback",
]

# Bazı bildirimler title'da geçmeyebiliyor; detail tarafında da arayacağız.
DETAIL_TEXT_FIELDS = [
    ("subject", "tr"),
    ("subject", "en"),
    ("summary", "tr"),
    ("summary", "en"),
]


def log(msg: str) -> None:
    if DEBUG:
        print(msg, flush=True)


def get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(
        f"{BASE_URL}{path}",
        params=params,
        auth=AUTH,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    # Hata olursa body'yi de loglamak çok yardımcı olur
    if r.status_code >= 400:
        log(f"HTTP {r.status_code} for {path} params={params} body={r.text[:1000]}")
    r.raise_for_status()
    return r.json()


def normalize_list(resp: Any) -> List[Dict[str, Any]]:
    """
    API bazen liste bazen objeyle dönebilir. Senin eski fonksiyonunun genişletilmişi.
    """
    if isinstance(resp, list):
        return [x for x in resp if isinstance(x, dict)]
    if isinstance(resp, dict):
        for k in ("data", "items", "disclosures"):
            v = resp.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def send_telegram(msg: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TG_BOT_TOKEN / TG_CHAT_ID eksik (Secrets ayarlı mı?)")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": msg,
            "disable_web_page_preview": False,
        },
        timeout=20,
    ).raise_for_status()


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def contains_keyword(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)


def extract_detail_text(detail: Dict[str, Any]) -> str:
    parts = []
    for a, b in DETAIL_TEXT_FIELDS:
        val = detail.get(a) or {}
        if isinstance(val, dict):
            parts.append(str(val.get(b) or ""))
    # Bazı durumlarda htmlMessages içinde metin olabilir
    html_messages = detail.get("htmlMessages")
    if isinstance(html_messages, list):
        for hm in html_messages[:5]:  # çok uzamasın
            if isinstance(hm, dict):
                parts.append(str(hm.get("tr") or ""))
                parts.append(str(hm.get("en") or ""))
    return " ".join(parts)


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(str(x))
    except Exception:
        return default


def get_last_disclosure_index() -> int:
    resp = get_json("/lastDisclosureIndex")
    return safe_int(resp.get("lastDisclosureIndex"), 0)


def fetch_disclosures_from(start_index: int,
                           disclosure_class: Optional[str] = None,
                           disclosure_types: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    /disclosures: start_index'ten itibaren ilk 50 bildirimi döndürür. :contentReference[oaicite:1]{index=1}
    """
    params: Dict[str, Any] = {"disclosureIndex": str(start_index)}
    if disclosure_class:
        params["disclosureClass"] = disclosure_class
    if disclosure_types:
        params["disclosureTypes"] = disclosure_types

    resp = get_json("/disclosures", params=params)
    return normalize_list(resp)


def fetch_detail(disclosure_index: int) -> Dict[str, Any]:
    # fileType zorunlu: html|data :contentReference[oaicite:2]{index=2}
    return get_json(f"/disclosureDetail/{disclosure_index}", params={"fileType": "html"})


def build_message(detail: Dict[str, Any]) -> str:
    sender = detail.get("senderTitle") or "-"
    subj = (detail.get("subject") or {}).get("tr") or (detail.get("subject") or {}).get("en") or "-"
    link = detail.get("link") or "-"
    t = detail.get("time") or ""
    summary_tr = (detail.get("summary") or {}).get("tr") or ""
    summary_tr = summary_tr.strip()
    if len(summary_tr) > 400:
        summary_tr = summary_tr[:400] + "…"

    msg = (
        "📢 PAY GERİ ALIMI / BUYBACK BİLDİRİMİ\n\n"
        f"Şirket: {sender}\n"
        f"Başlık: {subj}\n"
        f"Saat: {t}\n"
        f"Link: {link}\n"
    )
    if summary_tr:
        msg += f"\nÖzet: {summary_tr}\n"
    return msg

def main() -> None:
    if not API_KEY or not API_SECRET:
        raise RuntimeError("KAP_API_KEY / KAP_API_SECRET eksik (Secrets ayarlı mı?)")

    state = load_state()
    last_seen = safe_int(state.get("last_seen_index"), 0)

    current_last = get_last_disclosure_index()
    log(f"current_last={current_last}, last_seen={last_seen}")

    # SADECE İLERİYE YÖNELİK MOD:
    # İlk çalıştırmada geçmişi tarama, mevcut son index'i işaretle ve çık.
    if last_seen <= 0:
        state["last_seen_index"] = current_last
        state["updated_at_unix"] = int(time.time())
        save_state(state)
        log(f"First run (forward-only). Set last_seen_index={current_last} and exit.")
        return

    found_any = False
    max_processed = last_seen

    # ✅ Burada start yok: sadece yeni gelenlerden başla
    idx = last_seen + 1

    while idx <= current_last:
        log(f"[BATCH] idx={idx} / current_last={current_last}")

        items = fetch_disclosures_from(idx)
        log(f"[BATCH] got {len(items)} items")

        if not items:
            log(f"No items returned for idx={idx} (break)")
            break

        batch_max = idx

        for i, d in enumerate(items, start=1):
            di = safe_int(d.get("disclosureIndex"), 0)
            log(f"  [ITEM {i}/{len(items)}] disclosureIndex={di}")

            if di <= 0:
                continue

            if di > batch_max:
                batch_max = di

            # zaten işlendiyse atla
            if di <= last_seen:
                continue

            title = str(d.get("title") or "")
            quick_hit = contains_keyword(title)

            try:
                detail = fetch_detail(di)
            except Exception as e:
                log(f"detail fetch failed di={di}: {e}")
                continue

            detail_text = extract_detail_text(detail)
            hit = quick_hit or contains_keyword(detail_text)

            if hit:
                msg = build_message(detail)
                send_telegram(msg)
                found_any = True

            if di > max_processed:
                max_processed = di

            time.sleep(SLEEP)

        if batch_max <= idx:
            log(f"batch_max ({batch_max}) <= idx ({idx}) (break)")
            break

        idx = batch_max + 1
        time.sleep(SLEEP)

    state["last_seen_index"] = max_processed if max_processed > 0 else current_last
    state["updated_at_unix"] = int(time.time())
    save_state(state)

    log(f"done. found_any={found_any}, saved last_seen_index={state['last_seen_index']}")

if __name__ == "__main__":
    main()
