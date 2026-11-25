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
    "balance": {"kese", "kesem", "kase", "hazine", "bakiye", "tane"},
    "code": {"kod", "kodum", "ikram", "ikramim"},
    "optin": {"evet"},
    "optout": {"durdur", "stop", "iptal", "hayir", "hayir, tesekkurler"},
}


def keyword_intent(text):
    t = norm_text(text).strip(" .!«»\"'")
    for intent, words in KEYWORDS.items():
        if t in words:
            return intent
    return False


def bean_row(beans, small_at, cycle_len):
    """● ● ● ○ up to the next gift."""
    total = small_at if beans < small_at else cycle_len
    beans = max(0, min(beans, total))
    return " ".join(["●"] * beans + ["○"] * (total - beans))


def fmt_token(token):
    return " ".join(token[i:i + 4] for i in range(0, len(token), 4))


GIFT_NAMES = {"small": "Şefin İkramı", "big": "Hazine Tabağı"}

# Customer-facing texts (Turkish). "siz" form, only the ✦ mark, hospitality words (ikram, misafir).
MESSAGES = {
    "prelaunch": "Kakao Hazinesi {day}'ta açılıyor ✦ Taneniz şimdiden kesenizde, sizi bekliyor.",
    "welcome": "Kakao Hazinesi'ne hoş geldiniz{name} ✦\nFişinizden 1 tane + hoş geldin hediyesi 1 tane = 2 tane.\n{row}\n{gift}'na {left} tane kaldı.",
    "consent": "İkramınız hazır olduğunda WhatsApp'tan haber verelim mi? «Evet» ya da «Hayır» yazmanız yeterli.\nAydınlatma metni: {kvkk_url}",
    "credit": "Kakao taneniz kesenize eklendi ✦\n{row}\n{gift}'na {left} tane kaldı.",
    "gift_small": "Dördüncü kakao taneniz kesenizde ✦\nŞefin İkramı sizi bekliyor: menümüzde yer almayan, yalnızca Kakao Hazinesi misafirlerimize hazırladığımız küçük bir lezzet.\nBir sonraki gelişinizde sipariş verirken bu kodu göstermeniz yeterli:\n{token}\nSon gün: {expiry}",
    "gift_big": "Keseniz doldu ✦\nHazine Tabağı artık sizin: menüde bulamayacağınız, şefimizin özel tabağı.\nBir sonraki gelişinizde sipariş verirken bu kodu göstermeniz yeterli:\n{token}\nSon gün: {expiry}\nKeseniz yeni taneler için yeniden açıldı.",
    "balance": "Kesenizde {beans} kakao tanesi var ✦\n{row}\n{gift}'na {left} tane kaldı.",
    "code_line": "{gift} kodunuz: {token} (son gün {expiry})",
    "no_code": "Şu an bekleyen bir ikramınız yok. {gift}'na {left} tane kaldı.",
    "used": "Bu fişin tanesi daha önce bir keseye eklenmiş. Bir karışıklık varsa buradan yazın, hemen bakalım.",
    "expired": "Bu fişin süresi dolmuş. Bir sonraki gelişinizde taneniz sizi bekliyor olacak.",
    "invalid": "Bu kodu bulamadık. Fişteki QR'ı bir kez daha okutabilir misiniz?",
    "pending": "Hesabınız kapandığında taneniz kesenize kendiliğinden eklenecek ✦",
    "daily": "Bugünkü taneniz zaten kesenizde. Yarın görüşmek üzere ✦",
    "small_order": "Bu fiş Kakao Hazinesi'ne dahil değil. Yine bekleriz ✦",
    "optin": "Teşekkür ederiz. İkramınız hazır olduğunda haber vereceğiz ✦",
    "optout": "Bilgilendirme mesajlarını durdurduk. Keseniz aynen devam ediyor.",
}
