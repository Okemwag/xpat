"""Remove contact details from text before it is sent to an external AI service.

Only patterns that can be removed reliably are redacted: e-mail addresses and phone numbers. People's
names cannot be removed reliably, so the interface tells the user that the remaining text is sent.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Kenyan and international formats: +254 (20) 555-0147, 0722 123 456, +44 20 7946 0958 …
PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){1,3}(?!\w|\.\d)"
)


def _looks_like_phone(match):
    digits = re.sub(r"\D", "", match)
    has_marker = match.lstrip().startswith(("+", "(", "0"))
    return (
        9 <= len(digits) <= 15
        and has_marker
        and not re.fullmatch(r"\d{1,3}(,\d{3})+", match.strip())
    )


def redact(text):
    """Return (redacted_text, counts)."""
    emails = EMAIL.findall(text)
    text = EMAIL.sub("[email removed]", text)
    phones = 0

    def phone(m):
        nonlocal phones
        if _looks_like_phone(m.group(0)):
            phones += 1
            return "[phone removed]"
        return m.group(0)

    text = PHONE.sub(phone, text)
    return text, {"emails": len(emails), "phones": phones}
