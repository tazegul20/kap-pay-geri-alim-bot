import os
import requests
from requests.auth import HTTPBasicAuth

BASE_URL = "https://apigwdev.mkk.com.tr/api/vyk"

API_KEY = os.getenv("KAP_API_KEY")
API_SECRET = os.getenv("KAP_API_SECRET")
AUTH = HTTPBasicAuth(API_KEY, API_SECRET)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

KEYWORDS = [
    "geri al", "geri alım", "geri alin", "geri alim",
    "geri alınan pay", "geri alinan pay",
    "payların geri alımı", "paylarin geri alimi",
    "share buyback", "buyback"
]

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
        for k in ("data", "items", "disclosures"):
            if k in resp and isinstance(resp[k], list):
                return resp[k]
    return []

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "disable_web_page_preview": False
    }, timeout=20).raise_for_status()

def main():
    last_index = int(get_json("/lastDisclosureIndex")["lastDisclosureIndex"])
    items = normalize_list(get_json("/disclosures", {"disclosureIndex": last_index}))

    for d in items:
        if d.get("disclosureType") != "ODA":
            continue
        if d.get("disclosureClass") != "ODA":
            continue

        title = (d.get("title") or "").lower()
        if not any(k in title for k in KEYWORDS):
            continue

        di = d["disclosureIndex"]
        detail = get_json(f"/disclosureDetail/{di}")

        msg = (
            "📢 PAY GERİ ALIMI BİLDİRİMİ\n\n"
            f"Şirket: {detail.get('senderTitle')}\n"
            f"Başlık: {(detail.get('subject') or {}).get('tr')}\n"
            f"Link: {detail.get('link')}"
        )

        send_telegram(msg)
        break  # aynı run’da sadece 1 bildirim

if __name__ == "__main__":
    main()
