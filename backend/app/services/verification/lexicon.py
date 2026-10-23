"""Words the verifier must recognise in many languages (ruling R12): number words it cannot read,
negations, Vietnamese-specific letters, and one form for every dash.

Each check only ever turns a match into `unverified`; none of them can make a match succeed."""

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

from app.services.verification.numbers import nfkc

PUNCT = ".,;:!?()[]{}\"'"


def clean(text: str) -> str:
    """R12b + R15: NFKC with superscripts kept apart ('10²' is '10^2'), every dash ('‐', '—', '−') as '-'."""
    return nfkc(text)


def fold(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


# ---- R12d: number words of languages numbers.py cannot read ---------------------------------------
# Stems match as a prefix of a token, so compounds are caught ('veintitrés', 'ottantatré', 'dreißig').
# Stems that are, or begin, common English words ('un' until, 'mil' milk, 'cent' centimeter, 'doze'
# dozen, 'nove' novel, 'venti' ventilate, 'quarant' quarantine, 'mille' millet...) match only the whole
# token; those whole words still collide ('once', 'due', 'um', 'tre' = Vietnamese 'bamboo').
_STEMS = {
    "fr": "deux trois quatre cinq huit neuf onze douze treize quatorze quinze vingt trente quarante "
    "cinquante soixante septante huitante octante nonante",
    "es": "cuatro cinco seis siete ocho nueve diez trece catorce quince dieci veint treinta cuarenta "
    "cincuenta sesenta setenta ochenta noventa cien quinient",
    "it": "quattro cinque sette undici dodici tredici quattordici quindici sedici diciass diciott diciann "
    "ventid ventit ventiq ventic ventis ventin trent quaranta cinquant sessant settant ottant novant cento",
    "de": "zwei drei vier funf sechs sieben acht neun zehn zwolf zwanzig dreiss vierzig funfzig sechzig "
    "siebzig achtzig neunzig hundert tausend sechz siebz fuenf zwoelf",
    "pt": "dois duas quatro cinco seis sete oito treze catorze quinze dezesseis dezessete dezoito "
    "dezenove vinte trinta quarenta cinquenta sessenta setenta oitenta noventa cento dezas dezan",
}
_WHOLE = (
    "un une six sept dix seize cent mille uno una dos tres once doce mil due tre sei otto nove "
    "venti ventuno ventotto quarantuno quarantotto mila ein eins elf um uma dez onze doze cem "
    "einhundert eintausend zwo"
)
# R13: hundreds and thousands are compounds ('doscientos', 'duecento', 'duemila', 'quinhentos')
SUFFIXES = ("cientos", "cento", "centos", "zentos", "hentos", "mila", "hundert", "tausend")
STEMS = tuple(sorted({w for spec in _STEMS.values() for w in spec.split()}))
WHOLE = set(_WHOLE.split())
GERMAN_TENS = ("zig", "ssig")  # 'einundzwanzig', 'dreiunddreissig'
# substrings: Hangul numerals (native and Sino-Korean) and CJK numerals, glued to counters or not
HANGUL = "하나 한 둘 두 셋 세 넷 네 다섯 여섯 일곱 여덟 아홉 열 스물 서른 마흔".split()
HANGUL += "일 이 삼 사 오 육 칠 팔 구 십 백 천 만".split()
HANGUL += "스무 쉰 예순 일흔 여든 아흔 석 넉".split()  # R13
CJK = "一二三四五六七八九十百千万两半兩萬零〇廿卅壹贰貳叁參肆伍陆陸柒捌玖拾佰仟"


def foreign_number_word(token: str) -> bool:
    """R12d: the token is (or contains, for Hangul/CJK) a number word of fr/es/it/de/pt/ko/ja/zh."""
    word = clean(token).casefold().strip(PUNCT)
    if any(c in CJK for c in word) or any(h in word for h in HANGUL):
        return True
    for part in re.findall(r"[^\W\d_]+", fold(word)):
        if part in WHOLE or part.startswith(STEMS) or part.endswith(SUFFIXES):
            return True
        if part.endswith(GERMAN_TENS) and "und" in part:
            return True
    return False


def digits_with_foreign_words(text: str) -> bool:
    """R12d: a digit and a foreign number word in the same text ('2 ou trois', '10 bis fünfzehn')."""
    return bool(re.search(r"\d", text)) and any(foreign_number_word(t) for t in text.split())


# ---- R12a: letters only Vietnamese uses ------------------------------------------------------------
_VI_MARKS = {"̆", "̂", "̛", "̉", "̣"}  # breve, circumflex, horn, hook, dot below


def vietnamese_letter(token: str) -> bool:
    """ă â đ ê ô ơ ư (any tone) or a vowel with hook above / dot below; not é, è, ü, ã."""
    return any(c in "đĐ" or _VI_MARKS & set(unicodedata.normalize("NFD", c)) for c in token)


# ---- R12f: negations as (NEG, next word) pairs -----------------------------------------------------
NEGATIONS = {
    "not",
    "no",
    "never",
    "without",
    "cannot",
    "không",
    "đừng",
    "chớ",
    "chưa",
    "chẳng",
    "khỏi",
    "chả",
}
NEGATIONS |= {"ne", "pas", "jamais", "nunca", "nicht", "kein", "keine", "non", "não"}  # fr es de it pt
DECIMAL_WORDS = {"phẩy", "chấm"}
NOT_FORMS = {"cannot", "dont", "doesnt", "didnt", "cant", "wont", "shouldnt", "isnt", "arent"}


def _words(text: str) -> list[str]:
    raw = clean(text).casefold().replace("’", "'").split()
    return [w.strip(PUNCT) for w in raw if w.strip(PUNCT)]


# R15: on OCR text, a misread 'không' ('Kh0ng', 'Khônq', 'Khóng') or 'đừng' ('Dừng', 'Đưng') still
# negates: any token one edit from 'không'/'khong', or a token with a mark one edit from 'đừng'/'dung'.
# Common words one edit away by a letter OCR does not confuse, plus 'dùng'/'dụng' ('use', the usual word
# behind folded 'dung'), are left out; a negation misread into exactly one of them stays unseen.
OCR_NOT, OCR_DONT = ("không", "khong"), ("đừng", "dung")
OCR_WORDS = set(
    "khoảng khoang khung khùng phong chong thong hong khang khôn dùng dụng đang đông đồng đóng đăng "
    "từng vừng gừng rừng mừng dâng".split()
)


def _edits(a: str, b: str) -> int:
    return Levenshtein.distance(a, b, score_cutoff=2)


def _ocr_negation(word: str) -> bool:
    if word in OCR_WORDS:
        return False
    if any(_edits(word, w) <= 1 for w in OCR_NOT):
        return True
    return fold(word) != word and any(_edits(word, w) <= 1 for w in OCR_DONT)


def _negation(words: list[str], i: int, number_words, decimals: bool, ocr: bool = False) -> bool:
    word = "không" if words[i] == "khong" else words[i]  # OCR without diacritics; no other reading
    nxt, then = (words[i + 1 : i + 3] + ["", ""])[:2]
    if word == "không" and (nxt in number_words or nxt[:1].isdigit()):
        return False  # 'không trăm' is a digit
    if word == "không" and decimals and nxt in DECIMAL_WORDS and (then in number_words or then[:1].isdigit()):
        return False  # R12e: for a quantity, 'không phẩy năm' is 0.5; for a claim it still negates
    if word.endswith("n't") or word in NOT_FORMS or word in NEGATIONS:
        return True
    return ocr and _ocr_negation(word)


def negation_pairs(
    text: str, number_words, decimals: bool = False, ocr: bool = False
) -> set[tuple[str, str]]:
    """Each negation with the next word that is not a negation, all negations as one class:
    'không chạm' and 'đừng chạm' agree, 'không chấm' and 'không ướp' do not ('ne pas X' is one).

    R15: the next word is compared as written ('không chạm' is not 'không chấm'); `ocr` text loses its
    marks, so there it is folded, and misread negations count."""
    words = _words(text)
    marks = [_negation(words, i, number_words, decimals, ocr) for i in range(len(words))]
    out = set()
    for i, neg in enumerate(marks):
        if neg:
            after = next((w for w, m in zip(words[i + 1 :], marks[i + 1 :]) if not m), "")
            out.add(("NEG", fold(after) if ocr else after))
    return out
