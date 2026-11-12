"""Mask personal payment details before an LLM call, and flag suspicious buyer text.

Masking only changes what the provider sees. Validation still runs on the
original messages: `mask_text` keeps, for every masked character, the span of
original text it stands for, so a quote copied from masked text can be traced
back to the merchant's real words.

Injection flags are deterministic labels for buyer messages. They never block
extraction; the code validators already prevent buyer text from becoming a
promise. PayPal identifiers (capture, order, invoice, dispute IDs) are kept
because they are needed to act on a case and are not personal payment details.
"""

from app.schemas.privacy import (
    InjectionFlag as InjectionFlag,
)


import re


CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
BANK_ACCOUNT = re.compile(
    r"\b(?:a/c|ac|acct|account|bank\s+account|khata)\.?(?:\s*(?:no\.?|number|num|#))?\s*[:\-]?\s*"
    r"(\d[\d -]{7,20}\d)(?!\d)",
    re.IGNORECASE,
)
# Indian bank branch codes: 4 letters, a zero, 6 letters or digits. Uppercase
# alone, or any case right after the word "IFSC".
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
IFSC_LABELLED = re.compile(
    r"\bifsc\b\s*(?:code)?\s*[:\-]?\s*([a-z]{4}0[a-z0-9]{6})\b", re.IGNORECASE
)
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
UPI = re.compile(
    r"(?<![\w.@-])[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}(?![\w.@-])"
)
PHONES = (
    re.compile(r"(?<![\w+])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    re.compile(r"(?<![\w])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)"),
    re.compile(r"(?<![\w(])\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
)


def _luhn(digits):
    total = 0
    for position, digit in enumerate(int(d) for d in reversed(digits)):
        if position % 2:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def _sensitive_spans(text):
    """(start, end, label) for each detail to mask; earlier kinds win overlaps."""
    found = []

    def add(start, end, label):
        if not any(start < e and s < end for s, e, _ in found):
            found.append((start, end, label))

    # A labelled account number is checked first: some pass the card checksum.
    for match in BANK_ACCOUNT.finditer(text):
        digits = re.sub(r"\D", "", match.group(1))
        if 9 <= len(digits) <= 18:
            add(match.start(1), match.end(1), "bank_account")
    for match in CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            add(match.start(), match.end(), "card")
    for match in IFSC_LABELLED.finditer(text):
        add(match.start(1), match.end(1), "ifsc")
    for match in IFSC.finditer(text):
        add(match.start(), match.end(), "ifsc")
    for match in EMAIL.finditer(text):
        add(match.start(), match.end(), "email")
    for match in UPI.finditer(text):
        add(match.start(), match.end(), "upi_id")
    for pattern in PHONES:
        for match in pattern.finditer(text):
            if len(re.sub(r"\D", "", match.group())) >= 8:
                add(match.start(), match.end(), "phone")
    return sorted(found)


def mask_text(text):
    """Return (masked text, origin, counts).

    `origin[i]` is the (start, end) span of `text` that masked character i
    stands for: a single character for unchanged text, or the whole masked
    detail for each character of its placeholder.
    """
    masked, origin, counts, cursor = [], [], {}, 0
    for start, end, label in _sensitive_spans(text):
        for index in range(cursor, start):
            masked.append(text[index])
            origin.append((index, index + 1))
        placeholder = f"[{label}]"
        masked.extend(placeholder)
        origin.extend([(start, end)] * len(placeholder))
        counts[label] = counts.get(label, 0) + 1
        cursor = end
    for index in range(cursor, len(text)):
        masked.append(text[index])
        origin.append((index, index + 1))
    return "".join(masked), origin, counts


INJECTION_RULES = (
    (
        "RG-INJ-001",
        "Fake system or admin message",
        (
            r"(?:^|[\s\[<(#|])(?:system|admin(?:istrator)?)\s*(?:override|note|message|instruction)?\s*[:\]>|)]"
            r"|<\|system\|>|#{2,}\s*system|\bsystem\s+(?:override|prompt|instruction)"
            r"|\badmin\s+(?:note|message|override)\b|\bsystem\s+ko\s+(?:batao|bolo)\b"
        ),
    ),
    (
        "RG-INJ-002",
        "Claims authority",
        (
            r"\b(?:i\s*(?:am|'m)|this\s+is)\s+(?:the\s+)?(?:store\s+|shop\s+|merchant'?s\s+)?"
            r"(?:manager|owner|ceo|admin|lawyer|attorney)\b"
            r"|\bpaypal\s+(?:compliance|support|security|legal)\b|\bseller\s*\(verified\)"
            r"|\bmerchant\s+team\b|\byour\s+(?:ceo|manager|owner|boss)\s+(?:told|said|promised)\b"
            r"|\b(?:main|mai|mein)\s+(?:manager|owner|admin|malik)\s+(?:hoon|hun|hu|hai)\b"
        ),
    ),
    (
        "RG-INJ-003",
        "Asks to mark a refund or payment as done",
        (
            r"\bmark\s+(?:[\w#-]+\s+){0,3}?(?:as\s+)?(?:refunded|paid|resolved|completed|approved)\b"
            r"|\b(?:approve|issue|process)\s+(?:a\s+|the\s+|my\s+)?(?:full\s+)?(?:\$\s?\d[\d,.]*\s+)?refund\s+"
            r"(?:immediately|now|right\s+away)\b"
            # A claim that a refund is approved, but not a buyer asking whether it is.
            r"|\brefund\s+(?:of\s+\$?\d[\d,.]*\s+)?(?:is\s+|has\s+been\s+|was\s+)?(?:approved|confirmed)\b(?![^.!\n]*\?)"
            r"|\brefund(?:ed)?\s+(?:approve|mark|confirm)\s+kar(?:o|do|dena|dijiye)?\b"
            r"|\brefunded\s+mark\s+kar(?:o|do|dijiye)?\b"
        ),
    ),
    (
        "RG-INJ-004",
        "Quotes the merchant",
        (
            r"\b(?:merchant|seller|agent|support|your\s+(?:agent|colleague|team|chat\s*bot|bot|email))\s+"
            r"(?:said|says|wrote|promised|told\s+me)\s*:?\s*[\"“']"
            r"|(?:^|\n)\s*\[?(?:merchant|seller)\]?\s*:\s|\b(?:you|u)\s+(?:promised|said|wrote)\s*:\s*[\"“']"
            r"|\bmerchant\s+ne\s+(?:bola|kaha|promise|vaada)\b|\baapne\s+(?:bola|kaha)\s+tha\b"
        ),
    ),
    (
        "RG-INJ-005",
        "Tries to override instructions",
        (
            r"\bignore\s+(?:all\s+)?(?:the\s+)?(?:previous\s+|prior\s+|above\s+|earlier\s+)?(?:instructions|rules|prompts?)\b"
            r"|\bdisregard\s+(?:your|all|the)\s+(?:rules|instructions)\b|\bnew\s+task\s*:|\byou\s+are\s+now\b"
            r"|\bdeveloper\s+mode\b|\brules?\s+ignore\s+kar(?:o|do)\b"
        ),
    ),
)
_COMPILED = tuple(
    (rule_id, label, re.compile(pattern, re.IGNORECASE))
    for rule_id, label, pattern in INJECTION_RULES
)


def injection_flags(messages):
    """Flags for buyer messages matching an injection rule, in message order."""
    flags = []
    for message in messages:
        if message.sender != "buyer":
            continue
        for rule_id, label, pattern in _COMPILED:
            if pattern.search(message.text):
                flags.append(
                    InjectionFlag(rule_id=rule_id, label=label, message_id=message.id)
                )
    return flags
