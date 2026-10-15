"""Language support (English, Hindi, Kannada): fixed agent phrases, spoken-number normalisation.

Security-relevant replies (refusals, challenges, confirmations) always come from these templates -
never from the LLM - so they can't be hallucinated or prompt-injected.
"""
from __future__ import annotations

import re
import unicodedata

LANGS = ("en", "hi", "kn")

T: dict[str, dict[str, str]] = {
    "greeting": {
        "en": "Hello, I am Nishabdha, an AI voice agent. Open the approval center to verify my session and control my permissions. How can I help?",
        "hi": "नमस्ते, अनक्लोन बैंक में आपका स्वागत है। मैं आपकी क्या मदद कर सकती हूँ?",
        "kn": "ನಮಸ್ಕಾರ, ಅನ್‌ಕ್ಲೋನ್ ಬ್ಯಾಂಕ್‌ಗೆ ಸ್ವಾಗತ. ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
    },
    "greeting_outbound": {
        "en": "Hello {name}, I am Nishabdha, an AI voice agent. Verify my signed session in your approval center. The matching code is {code_spoken}; the code alone is not proof of identity.",
        "hi": "नमस्ते {name}, मैं अनक्लोन बैंक से बोल रही हूँ। यह कॉल असली है, इसकी पुष्टि के लिए आपके बैंक ऐप में कोड {code_spoken} दिख रहा है।",
        "kn": "ನಮಸ್ಕಾರ {name}, ಇದು ಅನ್‌ಕ್ಲೋನ್ ಬ್ಯಾಂಕ್. ಈ ಕರೆ ನಿಜವಾಗಿಯೂ ನಮ್ಮದು ಎಂದು ಖಚಿತಪಡಿಸಲು ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಆಪ್‌ನಲ್ಲಿ ಕೋಡ್ {code_spoken} ತೋರಿಸುತ್ತಿದೆ.",
    },
    "ask_identity": {
        "en": "Before I can help with your account, please tell me your registered mobile number.",
        "hi": "आपके खाते में मदद के लिए कृपया अपना रजिस्टर्ड मोबाइल नंबर बताइए।",
        "kn": "ನಿಮ್ಮ ಖಾತೆಗೆ ಸಹಾಯ ಮಾಡಲು ದಯವಿಟ್ಟು ನಿಮ್ಮ ನೋಂದಾಯಿತ ಮೊಬೈಲ್ ಸಂಖ್ಯೆಯನ್ನು ಹೇಳಿ.",
    },
    "identity_not_found": {
        "en": "I could not find an account with that number. Please say your registered mobile number again.",
        "hi": "उस नंबर से कोई खाता नहीं मिला। कृपया अपना रजिस्टर्ड मोबाइल नंबर फिर से बताइए।",
        "kn": "ಆ ಸಂಖ್ಯೆಯ ಖಾತೆ ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ನೋಂದಾಯಿತ ಮೊಬೈಲ್ ಸಂಖ್ಯೆಯನ್ನು ಮತ್ತೆ ಹೇಳಿ.",
    },
    "identity_ok": {
        "en": "Thank you {name}. What would you like to do?",
        "hi": "धन्यवाद {name}। आप क्या करना चाहेंगे?",
        "kn": "ಧನ್ಯವಾದಗಳು {name}. ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?",
    },
    "challenge": {
        "en": "For your security, please repeat these numbers after me: {digits_spoken}.",
        "hi": "आपकी सुरक्षा के लिए, कृपया ये अंक दोहराइए: {digits_spoken}।",
        "kn": "ನಿಮ್ಮ ಸುರಕ್ಷತೆಗಾಗಿ, ದಯವಿಟ್ಟು ಈ ಅಂಕಿಗಳನ್ನು ಪುನರಾವರ್ತಿಸಿ: {digits_spoken}.",
    },
    "challenge_retry": {
        "en": "Sorry, that did not match. Please repeat: {digits_spoken}.",
        "hi": "माफ़ कीजिए, मेल नहीं हुआ। कृपया दोहराइए: {digits_spoken}।",
        "kn": "ಕ್ಷಮಿಸಿ, ಹೊಂದಿಕೆಯಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಪುನರಾವರ್ತಿಸಿ: {digits_spoken}.",
    },
    "stepup": {
        "en": "I need one more confirmation. I have sent an approval request to the bank app on your registered phone. Please approve it or read me the code shown there.",
        "hi": "मुझे एक और पुष्टि चाहिए। आपके रजिस्टर्ड फ़ोन के बैंक ऐप पर अनुरोध भेजा है। कृपया उसे स्वीकार करें या वहाँ दिख रहा कोड बताइए।",
        "kn": "ನನಗೆ ಇನ್ನೊಂದು ದೃಢೀಕರಣ ಬೇಕು. ನಿಮ್ಮ ನೋಂದಾಯಿತ ಫೋನ್‌ನ ಬ್ಯಾಂಕ್ ಆಪ್‌ಗೆ ವಿನಂತಿ ಕಳುಹಿಸಿದ್ದೇನೆ. ದಯವಿಟ್ಟು ಅನುಮೋದಿಸಿ ಅಥವಾ ಅಲ್ಲಿ ಕಾಣುವ ಕೋಡ್ ಹೇಳಿ.",
    },
    "stepup_wrong": {
        "en": "That code is not correct. Please check the bank app and try again.",
        "hi": "यह कोड सही नहीं है। कृपया बैंक ऐप देखकर फिर से बताइए।",
        "kn": "ಆ ಕೋಡ್ ಸರಿಯಿಲ್ಲ. ದಯವಿಟ್ಟು ಬ್ಯಾಂಕ್ ಆಪ್ ನೋಡಿ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "refuse": {
        "en": "I'm sorry, I can't complete this request on this call. For your protection it has been put on hold and our fraud team will contact you on your registered number. Your money is safe.",
        "hi": "माफ़ कीजिए, यह अनुरोध इस कॉल पर पूरा नहीं हो सकता। आपकी सुरक्षा के लिए इसे रोक दिया गया है और हमारी फ्रॉड टीम आपके रजिस्टर्ड नंबर पर संपर्क करेगी। आपका पैसा सुरक्षित है।",
        "kn": "ಕ್ಷಮಿಸಿ, ಈ ಕರೆಯಲ್ಲಿ ಈ ವಿನಂತಿಯನ್ನು ಪೂರ್ಣಗೊಳಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ನಿಮ್ಮ ರಕ್ಷಣೆಗಾಗಿ ಇದನ್ನು ತಡೆಹಿಡಿಯಲಾಗಿದೆ ಮತ್ತು ನಮ್ಮ ವಂಚನೆ ತಂಡ ನಿಮ್ಮ ನೋಂದಾಯಿತ ಸಂಖ್ಯೆಗೆ ಸಂಪರ್ಕಿಸುತ್ತದೆ. ನಿಮ್ಮ ಹಣ ಸುರಕ್ಷಿತವಾಗಿದೆ.",
    },
    "need_more_audio": {
        "en": "I couldn't hear you clearly. Could you please say that again a little longer?",
        "hi": "मैं आपको साफ़ नहीं सुन पाई। कृपया थोड़ा विस्तार से फिर से कहिए।",
        "kn": "ನಿಮ್ಮ ಮಾತು ಸ್ಪಷ್ಟವಾಗಿ ಕೇಳಿಸಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ವಿವರವಾಗಿ ಮತ್ತೆ ಹೇಳಿ.",
    },
    "not_enrolled": {
        "en": "Your voice is not registered with us yet, so I will confirm this through your bank app instead.",
        "hi": "आपकी आवाज़ अभी हमारे पास पंजीकृत नहीं है, इसलिए मैं इसकी पुष्टि आपके बैंक ऐप से करूँगी।",
        "kn": "ನಿಮ್ಮ ಧ್ವನಿ ಇನ್ನೂ ನೋಂದಾಯಿತವಾಗಿಲ್ಲ, ಆದ್ದರಿಂದ ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಆಪ್ ಮೂಲಕ ದೃಢೀಕರಿಸುತ್ತೇನೆ.",
    },
    "done": {
        "en": "Done. {result}",
        "hi": "हो गया। {result}",
        "kn": "ಆಯಿತು. {result}",
    },
    "cancelled": {
        "en": "Okay, I have cancelled that request.",
        "hi": "ठीक है, मैंने वह अनुरोध रद्द कर दिया है।",
        "kn": "ಸರಿ, ಆ ವಿನಂತಿಯನ್ನು ರದ್ದುಗೊಳಿಸಿದ್ದೇನೆ.",
    },
    "missing_param": {
        "en": "Could you tell me {what}?",
        "hi": "क्या आप मुझे {what} बता सकते हैं?",
        "kn": "ದಯವಿಟ್ಟು {what} ಹೇಳುತ್ತೀರಾ?",
    },
    "bank_verify_sent": {
        "en": "Sure. I've sent a notification to your bank app. It should show the code {code_spoken}. If it does not, please hang up.",
        "hi": "ज़रूर। आपके बैंक ऐप पर सूचना भेजी है। उसमें कोड {code_spoken} दिखना चाहिए। अगर नहीं दिखे, तो कृपया कॉल काट दें।",
        "kn": "ಖಂಡಿತ. ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಆಪ್‌ಗೆ ಸೂಚನೆ ಕಳುಹಿಸಿದ್ದೇನೆ. ಅದರಲ್ಲಿ ಕೋಡ್ {code_spoken} ತೋರಿಸಬೇಕು. ಇಲ್ಲದಿದ್ದರೆ ದಯವಿಟ್ಟು ಕರೆ ಕಡಿತಗೊಳಿಸಿ.",
    },
    "pressure_warning": {
        "en": "Please take your time. The bank will never ask you to rush, share an OTP, or move money to a 'safe account'.",
        "hi": "कृपया जल्दबाज़ी न करें। बैंक कभी जल्दी करने, OTP बताने या पैसा 'सुरक्षित खाते' में भेजने को नहीं कहता।",
        "kn": "ದಯವಿಟ್ಟು ಆತುರಪಡಬೇಡಿ. ಬ್ಯಾಂಕ್ ಎಂದಿಗೂ ಆತುರಪಡಿಸುವುದಿಲ್ಲ, OTP ಕೇಳುವುದಿಲ್ಲ ಅಥವಾ ಹಣವನ್ನು 'ಸುರಕ್ಷಿತ ಖಾತೆ'ಗೆ ಕಳುಹಿಸಲು ಹೇಳುವುದಿಲ್ಲ.",
    },
    "goodbye": {
        "en": "Thank you for speaking with Nishabdha. Goodbye.",
        "hi": "अनक्लोन बैंक को कॉल करने के लिए धन्यवाद। नमस्ते।",
        "kn": "ಅನ್‌ಕ್ಲೋನ್ ಬ್ಯಾಂಕ್‌ಗೆ ಕರೆ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ವಂದನೆಗಳು.",
    },
    "fallback": {
        "en": "Sorry, I didn't get that. I can help with balance, transactions, cards, limits, mobile number updates, payees and transfers.",
        "hi": "माफ़ कीजिए, समझ नहीं पाई। मैं बैलेंस, लेन-देन, कार्ड, लिमिट, मोबाइल नंबर, पेयी और ट्रांसफ़र में मदद कर सकती हूँ।",
        "kn": "ಕ್ಷಮಿಸಿ, ಅರ್ಥವಾಗಲಿಲ್ಲ. ನಾನು ಬ್ಯಾಲೆನ್ಸ್, ವಹಿವಾಟುಗಳು, ಕಾರ್ಡ್‌ಗಳು, ಮಿತಿಗಳು, ಮೊಬೈಲ್ ಸಂಖ್ಯೆ, ಪೇಯಿ ಮತ್ತು ವರ್ಗಾವಣೆಗೆ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ.",
    },
    "call_locked": {
        "en": "For your security, account changes are no longer available on this call. Our fraud team will contact you on your registered number.",
        "hi": "आपकी सुरक्षा के लिए, इस कॉल पर अब खाते में बदलाव संभव नहीं है। हमारी फ्रॉड टीम आपके रजिस्टर्ड नंबर पर संपर्क करेगी।",
        "kn": "ನಿಮ್ಮ ಸುರಕ್ಷತೆಗಾಗಿ, ಈ ಕರೆಯಲ್ಲಿ ಖಾತೆ ಬದಲಾವಣೆಗಳು ಇನ್ನು ಲಭ್ಯವಿಲ್ಲ. ನಮ್ಮ ವಂಚನೆ ತಂಡ ನಿಮ್ಮ ನೋಂದಾಯಿತ ಸಂಖ್ಯೆಗೆ ಸಂಪರ್ಕಿಸುತ್ತದೆ.",
    },
}


def t(key: str, lang: str = "en", **kw) -> str:
    tpl = T.get(key, {})
    s = tpl.get(lang) or tpl.get("en") or key
    try:
        return s.format(**kw)
    except (KeyError, IndexError):
        return s


DIGIT_WORDS_SPOKEN = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
    "hi": ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ"],
    "kn": ["ಸೊನ್ನೆ", "ಒಂದು", "ಎರಡು", "ಮೂರು", "ನಾಲ್ಕು", "ಐದು", "ಆರು", "ಏಳು", "ಎಂಟು", "ಒಂಬತ್ತು"],
}


def speak_digits(digits: str, lang: str = "en") -> str:
    words = DIGIT_WORDS_SPOKEN.get(lang, DIGIT_WORDS_SPOKEN["en"])
    return ", ".join(words[int(d)] for d in digits if d.isdigit())


# Words (native script + common romanisations Whisper produces) -> digit
_WORD2DIGIT: dict[str, str] = {}
for _d, _ws in {
    "0": ["zero", "oh", "o", "nil", "shunya", "shoonya", "sunya", "sifar", "sonne", "sonné", "sone", "शून्य", "सिफ़र", "जीरो", "ज़ीरो", "ಸೊನ್ನೆ", "ಶೂನ್ಯ", "ಜೀರೋ"],
    "1": ["one", "won", "ek", "ekk", "ondu", "ond", "एक", "ಒಂದು", "ವನ್"],
    "2": ["two", "to", "too", "tu", "do", "doh", "eradu", "yeradu", "दो", "दों", "ಎರಡು", "ಎರಡ", "ಟೂ"],
    "3": ["three", "tree", "free", "teen", "tin", "mooru", "muru", "moru", "तीन", "ಮೂರು", "ಮೂರ", "ತ್ರೀ"],
    "4": ["four", "for", "fore", "char", "chaar", "naalku", "nalku", "naalaku", "चार", "ಚಾರ್", "ನಾಲ್ಕು", "ನಾಲಕು", "ನಾಕು", "ಫೋರ್"],
    "5": ["five", "fife", "paanch", "panch", "paach", "aidu", "aydu", "idu", "पाँच", "पांच", "पाच", "ಐದು", "ಅಯ್ದು", "ಫೈವ್"],
    "6": ["six", "sicks", "sex", "chhe", "che", "chhah", "chah", "chheh", "aaru", "aru", "छह", "छः", "छे", "ಆರು", "ಸಿಕ್ಸ್"],
    "7": ["seven", "saat", "sat", "saath", "elu", "yelu", "eelu", "सात", "ಏಳು", "ಎಳು", "ಯೇಳು", "साथ", "ಸೆವೆನ್"],
    "8": ["eight", "ate", "aath", "aat", "entu", "yentu", "ent", "आठ", "आट", "ಎಂಟು", "ಎಂಟ", "ಎಯ್ಟ್"],
    "9": ["nine", "nain", "nau", "now", "no", "ombattu", "ombathu", "ombhattu", "नौ", "नो", "ಒಂಬತ್ತು", "ಒಂಬತು", "ಒಂಭತ್ತು", "ನೈನ್"],
}.items():
    for _w in _ws:
        _WORD2DIGIT[_w] = _d

_NATIVE_NUMERALS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789")
_MULTIPLIERS = {"double": 2, "triple": 3, "डबल": 2, "ಡಬಲ್": 2}


def extract_digits(text: str) -> str:
    """'seven four two nine' / 'सात चार दो नौ' / 'ಏಳು 4 two' / 'double five' -> '7429'/'55'."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text).translate(_NATIVE_NUMERALS).lower()
    # split on spaces/punctuation (not \w: Indic vowel signs are combining marks, \w would cut words apart)
    tokens = re.findall(r"[0-9]+|[^\s\d.,;:!?\-\u0964\u0965'\"()]+", s)
    out: list[str] = []
    mult = 1
    for tok in tokens:
        if tok.isdigit():
            out.append(tok[0] * mult + tok[1:] if mult > 1 else tok)
            mult = 1
        elif tok in _MULTIPLIERS:
            mult = _MULTIPLIERS[tok]
        elif tok in _WORD2DIGIT:
            out.append(_WORD2DIGIT[tok] * mult)
            mult = 1
    return "".join(out)


def digits_match(expected: str, heard: str) -> tuple[bool, float]:
    """Exact digit sequence must appear; returns (match, similarity) - similarity used only for logging."""
    if not expected:
        return False, 0.0
    if expected in heard:
        return True, 1.0
    from rapidfuzz.distance import Levenshtein

    sim = Levenshtein.normalized_similarity(expected, heard[-len(expected) * 2 :] if heard else "")
    return False, round(float(sim), 3)


def detect_script_lang(text: str) -> str | None:
    if re.search(r"[ಀ-೿]", text or ""):
        return "kn"
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi"
    return None


def format_inr(paise: int) -> str:
    rupees = paise / 100
    neg = rupees < 0
    whole = f"{abs(int(round(abs(rupees)))):d}"
    # Indian grouping 12,34,567
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"{'-' if neg else ''}Rs {whole}"
