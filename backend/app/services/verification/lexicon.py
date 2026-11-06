"""Words the verifier must recognise in many languages (ruling R12): number words it cannot read,
negations, Vietnamese-specific letters, and one form for every dash.

Each check only ever turns a match into `unverified`; none of them can make a match succeed."""

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

from app.services.verification.numbers import nfkc

PUNCT = ".,;:!?()[]{}\"'"


def fold(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


# ---- R4c + X2: units -------------------------------------------------------------------------------
# canonical unit -> spellings, '|' between spellings. Only unambiguous ones: 'cân' (also 'scale'),
# 'lạng' (100 g), 'phân' (cm or manure), 'ly' and 'in' are left out, so they compare only as written.
UNIT_TABLE = {
    "sec": "giây|second|seconds|sec|secs|s",
    "min": "phút|minute|minutes|min|mins",
    "hour": "giờ|tiếng|hour|hours|hr|hrs|h",
    "day": "ngày|day|days",
    "week": "tuần|week|weeks",
    "g": "g|gram|grams|gam|gr|gm|gms",
    "kg": "kg|kilogram|kilograms|kilo|kilos|ký|kí",
    "ml": "ml|milliliter|milliliters|millilitre|millilitres|mililít",
    "l": "l|lít|liter|liters|litre|litres",
    "tbsp": "muỗng canh|thìa canh|tablespoon|tablespoons|tbsp|tbs",
    "tsp": "muỗng cà phê|thìa cà phê|teaspoon|teaspoons|tsp",
    "cup": "chén|cốc|cup|cups",
    "oz": "oz|ounce|ounces",  # X2: imperial units common in English recipes
    "floz": "fl oz|fluid ounce|fluid ounces",
    "lb": "lb|lbs",  # not 'pound', which is also money
    "pint": "pint|pints",
    "quart": "quart|quarts",
    "gallon": "gallon|gallons",
    "deg": "độ|degree|degrees|°",
    "degC": "°c|độ c|degree c|degrees c|degree celsius|degrees celsius|celsius",
    "degF": "°f|độ f|degree f|degrees f|degree fahrenheit|degrees fahrenheit|fahrenheit",
    "mm": "mm|millimeter|millimeters|millimetre|millimetres",
    "cm": "cm|centimeter|centimeters|centimetre|centimetres",
    "m": "m|mét|meter|meters|metre|metres",
    "inch": "inch|inches",
    "pct": "%|phần trăm|percent|per cent",
}
# X2: one-word, letters-only spellings, as written and without marks: the units split off a number they
# are glued to ('4tsp', '200g', '5phút'); 'x' ('2x'), ordinals ('1st') and 'k' are not units
GLUED_UNITS = {
    f for spec in UNIT_TABLE.values() for s in spec.split("|") if s.isalpha() for f in (s, fold(s))
}
_GLUED = re.compile(r"(?<![^\W_])(\d+(?:[.,/:]\d+)*)([^\W\d_]+)(?![^\W_])")


# ---- X1a: material names a dictionary can tie to the other language ---------------------------------
# Strict 1:1 Vietnamese <-> English for common cooking ingredients. The whole normalized name must be a
# key (or one of the English forms, for an English draft of a Vietnamese video). Left out on purpose:
# words with more than one meaning in the kitchen ('bột' flour/powder/batter, 'bơ' butter/avocado,
# 'dầu' oil/sauce base, 'chanh' lemon/lime, 'bột ngô' cornstarch/corn flour, 'kem' cream/ice cream) and
# names wider than one English word ('sữa tươi', 'thịt'). 'bột mì' is wheat flour; 'bột mì đa dụng' is
# all-purpose flour, its own entry.
INGREDIENTS = {
    "trứng": "egg|eggs",
    "lòng đỏ trứng": "egg yolk|egg yolks",
    "lòng trắng trứng": "egg white|egg whites",
    "sữa": "milk",
    "đường": "sugar",
    "đường nâu": "brown sugar",
    "muối": "salt",
    "tiêu": "pepper",
    "hạt tiêu": "pepper",
    "tiêu đen": "black pepper",
    "nước": "water",
    "bột mì": "flour",
    "bột mì đa dụng": "all purpose flour",
    "chiết xuất vani": "vanilla extract",
    "vani": "vanilla",
    "men": "yeast",
    "men nở": "yeast",
    "bột nở": "baking powder",
    "muối nở": "baking soda",
    "mật ong": "honey",
    "giấm": "vinegar",
    "tỏi": "garlic",
    "hành tây": "onion|onions",
    "hành lá": "scallion|scallions|green onion|green onions",
    "gừng": "ginger",
    "quế": "cinnamon",
    "gạo": "rice",
    "cà chua": "tomato|tomatoes",
    "khoai tây": "potato|potatoes",
    "cà rốt": "carrot|carrots",
    "nấm": "mushroom|mushrooms",
    "thịt bò": "beef",
    "thịt gà": "chicken",
    "thịt heo": "pork",
    "thịt lợn": "pork",
    "tôm": "shrimp|shrimps|prawn|prawns",
    "đậu phụ": "tofu",
    "phô mai": "cheese",
    "sô cô la": "chocolate",
    "nước mắm": "fish sauce",
    "nước tương": "soy sauce",
    "xì dầu": "soy sauce",
    "dầu hào": "oyster sauce",
    "bột năng": "tapioca starch",
}
# words that may stand right before or after the ingredient in the source without changing which one it
# is: numbers and units (checked separately), articles, 'of', and kitchen verbs; anything else ('coconut'
# milk, 'rice' flour, 'bell' pepper, egg 'yolks', vanilla 'extract') may name another ingredient
NEIGHBOURS = set(
    "a an the of some more little bit few your our my this that these those it here now then just also "
    "add adds adding added pour mix whisk stir put throw use using in into to for over on plus "
    "cho thêm vào bỏ đổ rồi nhé là một ít chút các những này đó trong lên".split()
)


# X6: words that join two items, so a name past one of them belongs to another item
CONJUNCTIONS = set("and plus then or with và va rồi roi hoặc hoac hay với voi sau cùng cung".split())


def _phrases(spec: str) -> list[list[str]]:
    return [re.findall(r"[^\W_]+", p) for p in spec.split("|")]


_TO_EN = {name: _phrases(en) for name, en in INGREDIENTS.items()}
_TO_VI: dict[str, list[list[str]]] = {}
for _vi, _en in INGREDIENTS.items():
    for _form in _en.split("|"):
        _TO_VI.setdefault(" ".join(re.findall(r"[^\W_]+", _form)), []).append(re.findall(r"[^\W_]+", _vi))


def ingredient_words(name: str) -> list[list[str]]:
    """X1a: the other language's word sequences for a material name, [] when it is not in INGREDIENTS."""
    key = " ".join(re.findall(r"[^\W_]+", clean(name).casefold()))
    return _TO_EN.get(key) or _TO_VI.get(key, [])


def khong_before_digit(text: str) -> bool:
    """X5a: 'không' (or OCR 'khong', 'kh0ng') right before a digit: for a quantity it is 'not' ('Không
    2 chén đường'); spoken zeros are read as number words ('không trăm', 'không phẩy năm'), not digits."""
    return bool(re.search(r"(?<!\w)(?:không|khong|kh0ng)\s+\d", clean(text).casefold()))


def split_units(text: str) -> str:
    """X2: a table unit glued to the number before it becomes its own word ('Milk 4tsp' -> 'Milk 4 tsp',
    '1/2tsp' -> '1/2 tsp'); the number is untouched, and a number glued to letters on its left ('mp3s'),
    a run continuing into digits ('1h30') or any other suffix ('2x', '4k', '1st') stays as written."""

    def cut(m: re.Match) -> str:
        return f"{m[1]} {m[2]}" if m[2].casefold() in GLUED_UNITS else m[0]

    return _GLUED.sub(cut, text)


def clean(text: str) -> str:
    """R12b + R15: NFKC with superscripts kept apart ('10²' is '10^2'), every dash ('‐', '—', '−') as '-';
    X2: a table unit glued to a number is split off it ('4tsp' is '4 tsp')."""
    return split_units(nfkc(text))


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
# R16a: only the frame text read by OCR is read this way, never the model's own words, so 'đúng',
# 'thông' or 'dừng' written by the model cannot stand in for a real 'đừng'/'không' on screen.
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


def _negation(words: list[str], i: int, number_words, decimals: bool, misread: bool = False) -> bool:
    word = "không" if words[i] == "khong" else words[i]  # OCR without diacritics; no other reading
    nxt, then = (words[i + 1 : i + 3] + ["", ""])[:2]
    if word == "không" and (nxt in number_words or nxt[:1].isdigit()):
        return False  # 'không trăm' is a digit
    if word == "không" and decimals and nxt in DECIMAL_WORDS and (then in number_words or then[:1].isdigit()):
        return False  # R12e: for a quantity, 'không phẩy năm' is 0.5; for a claim it still negates
    if word.endswith("n't") or word in NOT_FORMS or word in NEGATIONS:
        return True
    return misread and _ocr_negation(word)


def written_words(text: str) -> frozenset[str]:
    """The words of a text as negation_pairs reads them (casefolded, marks kept)."""
    return frozenset(_words(text))


def negation_pairs(
    text: str,
    number_words,
    decimals: bool = False,
    ocr: bool = False,
    frame: frozenset[str] | None = None,
) -> set[tuple[str, str]]:
    """Each negation with the next word that is not a negation, all negations as one class:
    'không chạm' and 'đừng chạm' agree, 'không chấm' and 'không ướp' do not ('ne pas X' is one).

    R15: the next word is compared as written ('không chạm' is not 'không chấm'); `ocr` text loses its
    marks, so there it is folded. R16a: `frame` is given only when `text` is the OCR frame itself; then a
    misread negation ('Kh0ng', 'Khóng', 'Dừng') counts too, except a word in `frame`, the words the model
    wrote exactly as the frame shows them ('Đúng 5 phút' on screen and in the claim text)."""
    words = _words(text)
    misread = [frame is not None and w not in frame for w in words]
    marks = [_negation(words, i, number_words, decimals, misread[i]) for i in range(len(words))]
    out = set()
    for i, neg in enumerate(marks):
        if neg:
            after = next((w for w, m in zip(words[i + 1 :], marks[i + 1 :]) if not m), "")
            out.add(("NEG", fold(after) if ocr else after))
    return out
