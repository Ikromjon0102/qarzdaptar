import re


def clean_phone_number(phone):
    """
    Telefon raqamni tozalab, +998XXXXXXXXX formatiga keltiradi.
    Agar format noto'g'ri bo'lsa, None qaytaradi.
    """
    # 1. Faqat raqamlarni qoldiramiz
    digits = re.sub(r'\D', '', phone)

    # 2. Uzunligini tekshiramiz
    if len(digits) == 9:  # 901234567 -> +998901234567
        return f"+998{digits}"
    elif len(digits) == 12 and digits.startswith('998'):  # 998901234567 -> +998901234567
        return f"+{digits}"

    # Boshqa holatlar xato deb hisoblanadi
    return None