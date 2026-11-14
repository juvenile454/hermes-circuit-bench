"""Hidden characters made visible as ``\\uXXXX`` (``\\UXXXXXXXX`` above U+FFFF).

Two uses:

- ``approval_tokens``: the paths and values of an approval question. Visible are control characters, format
  characters (direction marks, zero-width characters), lone surrogates, line and paragraph separators, every space
  other than U+0020, some blank letters (``BLANK_LETTERS``) and every Default_Ignorable_Code_Point. The quoted folder
  field also shows every quotation mark but the apostrophe and every look-alike of ``"`` as an escape
  (``FIELD_QUOTES``), so nothing in a folder name can look like the end of the field.
- ``for_model``: the message and hint of an error answer and the block messages of the approval hook. Visible are
  format characters, lone surrogates, line and paragraph separators, DEL and the C1 controls (U+007F-U+009F) and every
  Default_Ignorable_Code_Point. C0 controls (line breaks, tabs) and spaces stay as they are. Input is never refused
  because of such characters: zero-width joiners occur in real folder names.

Look-alike letters (homoglyphs) stay as they are.
"""
from __future__ import annotations

import bisect
import unicodedata
from collections.abc import Collection
from typing import Any

# Default_Ignorable_Code_Point, copied range by range from the Unicode Character Database:
# DerivedCoreProperties.txt, Unicode 18.0.0 (file date 2026-08-07),
# https://www.unicode.org/Public/18.0.0/ucd/DerivedCoreProperties.txt, retrieved 2026-11-14.
# Reserved code points of the list are included: a later Unicode version may assign them.
DEFAULT_IGNORABLE: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),    # SOFT HYPHEN
    (0x034F, 0x034F),    # COMBINING GRAPHEME JOINER
    (0x061C, 0x061C),    # ARABIC LETTER MARK
    (0x115F, 0x1160),    # HANGUL CHOSEONG FILLER..HANGUL JUNGSEONG FILLER
    (0x17B4, 0x17B5),    # KHMER VOWEL INHERENT AQ..KHMER VOWEL INHERENT AA
    (0x180B, 0x180D),    # MONGOLIAN FREE VARIATION SELECTOR ONE..THREE
    (0x180E, 0x180E),    # MONGOLIAN VOWEL SEPARATOR
    (0x180F, 0x180F),    # MONGOLIAN FREE VARIATION SELECTOR FOUR
    (0x200B, 0x200F),    # ZERO WIDTH SPACE..RIGHT-TO-LEFT MARK
    (0x202A, 0x202E),    # LEFT-TO-RIGHT EMBEDDING..RIGHT-TO-LEFT OVERRIDE
    (0x2060, 0x2064),    # WORD JOINER..INVISIBLE PLUS
    (0x2065, 0x2065),    # <reserved-2065>
    (0x2066, 0x206F),    # LEFT-TO-RIGHT ISOLATE..NOMINAL DIGIT SHAPES
    (0x3164, 0x3164),    # HANGUL FILLER
    (0xFE00, 0xFE0F),    # VARIATION SELECTOR-1..VARIATION SELECTOR-16
    (0xFEFF, 0xFEFF),    # ZERO WIDTH NO-BREAK SPACE
    (0xFFA0, 0xFFA0),    # HALFWIDTH HANGUL FILLER
    (0xFFF0, 0xFFF8),    # <reserved-FFF0>..<reserved-FFF8>
    (0x1BCA0, 0x1BCA3),  # SHORTHAND FORMAT LETTER OVERLAP..SHORTHAND FORMAT UP STEP
    (0x1D173, 0x1D17A),  # MUSICAL SYMBOL BEGIN BEAM..MUSICAL SYMBOL END PHRASE
    (0xE0000, 0xE0000),  # <reserved-E0000>
    (0xE0001, 0xE0001),  # LANGUAGE TAG
    (0xE0002, 0xE001F),  # <reserved-E0002>..<reserved-E001F>
    (0xE0020, 0xE007F),  # TAG SPACE..CANCEL TAG
    (0xE0080, 0xE00FF),  # <reserved-E0080>..<reserved-E00FF>
    (0xE0100, 0xE01EF),  # VARIATION SELECTOR-17..VARIATION SELECTOR-256
    (0xE01F0, 0xE0FFF),  # <reserved-E01F0>..<reserved-E0FFF>
)
_DI_STARTS = tuple(lo for lo, _hi in DEFAULT_IGNORABLE)

# blank letters that are no Default_Ignorable_Code_Point: BRAILLE PATTERN BLANK (the others of the former list,
# U+034F, U+115F, U+1160, U+3164 and U+FFA0, are Default_Ignorable_Code_Points)
BLANK_LETTERS = frozenset("\u034f\u115f\u1160\u3164\uffa0\u2800")
_APPROVAL_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp", "Zs"})  # control, format (direction marks), lone
# surrogates, line and paragraph separators, spaces (U+0020 itself stays)
_MODEL_CATEGORIES = frozenset({"Cf", "Cs", "Zl", "Zp"})  # format, lone surrogates, line and paragraph separators

# Quotation_Mark, copied range by range from the Unicode Character Database:
# PropList.txt, Unicode 18.0.0 (file date 2026-08-07), https://www.unicode.org/Public/18.0.0/ucd/PropList.txt,
# retrieved 2026-11-14.
QUOTATION_MARK: tuple[tuple[int, int], ...] = (
    (0x0022, 0x0022),  # QUOTATION MARK
    (0x0027, 0x0027),  # APOSTROPHE
    (0x00AB, 0x00AB),  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    (0x00BB, 0x00BB),  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
    (0x2018, 0x2018),  # LEFT SINGLE QUOTATION MARK
    (0x2019, 0x2019),  # RIGHT SINGLE QUOTATION MARK
    (0x201A, 0x201A),  # SINGLE LOW-9 QUOTATION MARK
    (0x201B, 0x201C),  # SINGLE HIGH-REVERSED-9 QUOTATION MARK..LEFT DOUBLE QUOTATION MARK
    (0x201D, 0x201D),  # RIGHT DOUBLE QUOTATION MARK
    (0x201E, 0x201E),  # DOUBLE LOW-9 QUOTATION MARK
    (0x201F, 0x201F),  # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    (0x2039, 0x2039),  # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    (0x203A, 0x203A),  # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    (0x2E42, 0x2E42),  # DOUBLE LOW-REVERSED-9 QUOTATION MARK
    (0x300C, 0x300C),  # LEFT CORNER BRACKET
    (0x300D, 0x300D),  # RIGHT CORNER BRACKET
    (0x300E, 0x300E),  # LEFT WHITE CORNER BRACKET
    (0x300F, 0x300F),  # RIGHT WHITE CORNER BRACKET
    (0x301D, 0x301D),  # REVERSED DOUBLE PRIME QUOTATION MARK
    (0x301E, 0x301F),  # DOUBLE PRIME QUOTATION MARK..LOW DOUBLE PRIME QUOTATION MARK
    (0xFE41, 0xFE41),  # PRESENTATION FORM FOR VERTICAL LEFT CORNER BRACKET
    (0xFE42, 0xFE42),  # PRESENTATION FORM FOR VERTICAL RIGHT CORNER BRACKET
    (0xFE43, 0xFE43),  # PRESENTATION FORM FOR VERTICAL LEFT WHITE CORNER BRACKET
    (0xFE44, 0xFE44),  # PRESENTATION FORM FOR VERTICAL RIGHT WHITE CORNER BRACKET
    (0xFF02, 0xFF02),  # FULLWIDTH QUOTATION MARK
    (0xFF07, 0xFF07),  # FULLWIDTH APOSTROPHE
    (0xFF62, 0xFF62),  # HALFWIDTH LEFT CORNER BRACKET
    (0xFF63, 0xFF63),  # HALFWIDTH RIGHT CORNER BRACKET
)

# look-alikes of the quotation mark: characters that can look like '"' but do not have the property Quotation_Mark
# (checked against the same PropList.txt: the primes are Pattern_Syntax/Other_Math, U+02BA, U+02DD and U+02EE are
# Diacritic, the others have no property there)
QUOTE_LOOKALIKES: tuple[tuple[int, int], ...] = (
    (0x02BA, 0x02BA),    # MODIFIER LETTER DOUBLE PRIME
    (0x02DD, 0x02DD),    # DOUBLE ACUTE ACCENT
    (0x02EE, 0x02EE),    # MODIFIER LETTER DOUBLE APOSTROPHE
    (0x05F4, 0x05F4),    # HEBREW PUNCTUATION GERSHAYIM
    (0x2032, 0x2037),    # PRIME..REVERSED TRIPLE PRIME
    (0x2057, 0x2057),    # QUADRUPLE PRIME
    (0x275B, 0x275E),    # HEAVY SINGLE TURNED COMMA QUOTATION MARK ORNAMENT..HEAVY DOUBLE COMMA QUOTATION MARK ORNAMENT
    (0x3003, 0x3003),    # DITTO MARK
    (0x1F676, 0x1F678),  # SANS-SERIF HEAVY (TURNED, LOW) DOUBLE COMMA QUOTATION MARK ORNAMENT
)

# the characters shown as escapes in a quoted field of an approval question (the firmware folder): every
# Quotation_Mark and every look-alike, except the apostrophe U+0027 (it does not end the field, which is quoted with
# '"', and occurs in folder names)
FIELD_QUOTES: frozenset[str] = frozenset(
    chr(cp) for lo, hi in (*QUOTATION_MARK, *QUOTE_LOOKALIKES) for cp in range(lo, hi + 1)) - {"'"}


def is_default_ignorable(ch: str) -> bool:
    """True for a character with the Unicode property Default_Ignorable_Code_Point (``DEFAULT_IGNORABLE``)."""
    cp = ord(ch)
    i = bisect.bisect_right(_DI_STARTS, cp) - 1
    return i >= 0 and cp <= DEFAULT_IGNORABLE[i][1]


def escape(ch: str) -> str:
    """``\\uXXXX`` (``\\UXXXXXXXX`` above U+FFFF) for one character."""
    return f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}"


def approval_hidden(ch: str) -> bool:
    """Is ``ch`` shown as an escape in an approval question?"""
    return ch != " " and (ch in BLANK_LETTERS or unicodedata.category(ch) in _APPROVAL_CATEGORIES
                          or is_default_ignorable(ch))


def approval_tokens(text: str, extra: Collection[str] = "") -> list[str]:
    """One display token per character of ``text``: hidden characters (``approval_hidden``) and the characters of
    ``extra`` (e.g. ``FIELD_QUOTES``) become escapes, the rest stays."""
    return [escape(ch) if ch in extra or approval_hidden(ch) else ch for ch in text]


def model_hidden(ch: str) -> bool:
    """Is ``ch`` shown as an escape in a message to the model?"""
    cp = ord(ch)
    if cp < 0x7F:
        return False  # printable ASCII and the C0 controls stay as they are
    return 0x7F <= cp <= 0x9F or unicodedata.category(ch) in _MODEL_CATEGORIES or is_default_ignorable(ch)


def for_model(text: Any) -> Any:
    """``text`` with the characters of ``model_hidden`` as escapes; anything that is not text is returned as is."""
    if not isinstance(text, str) or (text.isascii() and "\x7f" not in text):
        return text
    return "".join(escape(ch) if model_hidden(ch) else ch for ch in text)
