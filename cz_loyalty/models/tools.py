# -*- coding: utf-8 -*-
"""Pure helpers (no ORM): phone normalisation, codes, Turkish text matching."""
import re
import secrets
import unicodedata

# Crockford base32 without I, L, O, U: no look-alike characters on a receipt.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LEN = 8
CODE_RE = re.compile(r"ZUMA[\s\-_]*([0-9A-HJKMNP-TV-Z]{8})", re.IGNORECASE)


def new_order_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def new_reward_token():
    # Digits only: USB scanners act as keyboards and the Turkish Q layout garbles letters.
    return "99" + "".join(secrets.choice("0123456789") for _ in range(10))


def normalize_phone(raw):
    """Return +90XXXXXXXXXX for Turkish mobiles, +<digits> for others, or False."""
    if not raw:
        return False
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("05"):
        digits = "90" + digits[1:]
    elif len(digits) == 10 and digits.startswith("5"):
        digits = "90" + digits
    if len(digits) < 8 or len(digits) > 15:
        return False
    return "+" + digits


def norm_text(text):
    """Lowercase, Turkish-safe, accents removed: 'KÂSE', 'Kase', 'kâse' -> 'kase'."""
    if not text:
        return ""
    t = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def extract_code(text):
    if not text:
        return False
    m = CODE_RE.search(text.upper())
    return m.group(1).upper() if m else False


KEYWORDS = {
    "balance": {"kase", "hazine", "kasem", "bakiye"},
    "optin": {"evet"},
    "optout": {"durdur", "stop", "iptal", "hayir", "hayir, tesekkurler"},
}


def keyword_intent(text):
    t = norm_text(text)
    for intent, words in KEYWORDS.items():
        if t in words:
            return intent
    return False


# Customer-facing texts (Turkish). "siz" form, one emoji at most, no discount words.
MESSAGES = {
    "welcome": "Choco Zuma'ya hoş geldiniz ☀️ İlk kakao taneniz kâsenize eklendi: {beans}/{target}.\nSize nasıl hitap edelim?",
    "name_thanks": "Memnun olduk {name}. Her {target} ziyarette menüde olmayan bir Zuma Sürprizi sizi bekliyor.",
    "consent": "Size özel günlerden WhatsApp'tan haberdar olmak ister misiniz? Lütfen «Evet» ya da «Hayır» yazın.\nAydınlatma metni: {kvkk_url}",
    "credit": "+1 kakao tanesi 🍫 {beans}/{target}",
    "reward": "Kâseniz doldu {name}! Zuma Sürprizi sizi bekliyor: menüde olmayan, size özel bir tabak.\nBir sonraki ziyaretinizde bu kodu kasada gösterin: {token}\n{expiry} tarihine kadar geçerli.",
    "balance": "Kâsenizde {beans}/{target} kakao tanesi var.",
    "balance_reward": "Zuma Sürpriziniz hazır: {token} ({expiry} tarihine kadar geçerli).",
    "used": "Bu fişin tanesi daha önce bir kâseye eklenmiş. Bir karışıklık varsa yazın, hemen bakalım.",
    "expired": "Bu fişin süresi dolmuş. Bir sonraki ziyaretinizde taneniz sizi bekliyor olacak.",
    "invalid": "Bu kodu bulamadık. Fişteki QR'ı bir kez daha okutabilir misiniz?",
    "pending": "Fişiniz sisteme düştüğünde taneniz otomatik olarak eklenecek.",
    "daily": "Bugünün tanesi zaten kâsenizde. Yine bekleriz ✨",
    "small": "Bu fiş Kakao Hazinesi'ne dahil değil. Yine bekleriz.",
    "optin": "Teşekkürler. Size özel günlerde haber vereceğiz.",
    "optout": "Bilgilendirme mesajlarını durdurduk. Kâseniz aynen devam ediyor.",
}
