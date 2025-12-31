import os
import json
import requests
from requests.auth import HTTPBasicAuth

# =====================================================
# KAP API AYARLARI
# =====================================================
BASE_URL = "https://apigwdev.mkk.com.tr/api/vyk"

API_KEY = "c5a6bb4d-acdd-4c8c-92fb-b84813891746"
API_SECRET = "e754da6c-e305-4458-a5ef-a32aba858a6b"
AUTH = HTTPBasicAuth(API_KEY, API_SECRET)

# =====================================================
# TELEGRAM AYARLARI (SENİN VERDİKLERİN – ÖRNEK)
# =====================================================
BOT_TOKEN = "8428497929:AAH8cm9hHg4IPXpPH8f0h2qyuIdQYDPEGNA"
CHAT_ID = "6741905923"

# =====================================================
# FİLTRE AYARLARI – PAY GERİ ALIMI
# =====================================================
TARGET_TYPE = "ODA"
TARGET_CLASS = "ODA"

KEYWORDS = [
    "geri al", "geri alım", "geri alin", "geri alim",
    "geri alınan pay", "geri alinan pay",
    "payların geri alımı", "paylarin geri alimi",
    "share buyback", "buyback"
]

STATE_FILE = "kap_state.json"

# =====================================================
# YARDIMCI FONKSİYONLAR
# =====================================================
def get_json(path, params=None):
    r = requests.get(
        f"{BASE_URL}{path}",
        params=params,
        auth=AUTH,
        headers={"Accept": "application/json"},
        timeout=30
    )
    r.raise_for_status()
    return r.json()

def normalize_list(resp):
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("data", "items", "result", "disclosures"):
            if k in resp and isinstance(resp[k], list):
                return resp[k]
    return []

# =====================================================
# TELEGRAM
# =====================================================
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()

# =====================================================
# KAP ENDPOINTLERİ
# =====================================================
def last_disclosure_index() -> int:
    return int(get_json("/lastDisclosureIndex")["lastDisclosureIndex"])

def disclosures_page(disclosure_index: int):
    resp = get_json("/disclosures", params={"disclosureIndex": str(disclosure_index)})
    return normalize_list(resp)

def disclosure_detail(disclosure_index: int):
    return get_json(
        f"/disclosureDetail/{disclosure_index}",
        params={"fileType": "html"}
    )

# =====================================================
# STATE
# =====================================================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_seen": None}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

# =====================================================
# ANA KONTROL
# =====================================================
def check_once():
    state = load_state()
    last_seen = state["last_seen"]
    current_last = last_disclosure_index()

    # İlk çalıştırma → geçmişi spam yapmamak için
    if last_seen is None:
        state["last_seen"] = current_last
        save_state(state)
        print("İlk çalıştırma – state set edildi.")
        return

    if current_last <= last_seen:
        print("Yeni bildirim yok.")
        return

    cursor = current_last
    hits = []

    while cursor > last_seen:
        items = disclosures_page(cursor)
        if not items:
            break

        for d in items:
            di = int(d.get("disclosureIndex", 0))
            if di <= last_seen:
                continue

            if d.get("disclosureType") != TARGET_TYPE:
                continue
            if d.get("disclosureClass") != TARGET_CLASS:
                continue

            title = (d.get("title") or "").lower()
            if not any(k in title for k in KEYWORDS):
                continue

            hits.append(di)

        cursor = min(int(x["disclosureIndex"]) for x in items) - 1

    state["last_seen"] = current_last
    save_state(state)

    if not hits:
        print("Yeni pay geri alımı yok.")
        return

    di = max(hits)
    detail = disclosure_detail(di)

    sender = detail.get("senderTitle", "")
    subject = (detail.get("subject") or {}).get("tr", "")
    time_info = detail.get("time", "")
    link = detail.get("link", f"https://www.kap.org.tr/Bildirim/{di}")

    msg = (
        "📢 *PAY GERİ ALIMI BİLDİRİMİ*\n\n"
        f"🏢 *Şirket:* {sender}\n"
        f"📝 *Başlık:* {subject}\n"
        f"⏰ *Tarih/Saat:* {time_info}\n"
        f"🔗 *Link:* {link}\n"
        f"🆔 *DisclosureIndex:* {di}"
    )

    send_telegram(msg)
    print("Telegram bildirimi gönderildi:", di)

# =====================================================
# ÇALIŞTIR
# =====================================================
if __name__ == "__main__":
    check_once()

send_telegram("✅ Telegram test mesajı")
