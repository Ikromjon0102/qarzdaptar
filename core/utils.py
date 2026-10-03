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

def parse_amount(value):
    """
    Foydalanuvchi kiritgan summani songa aylantiradi.
    "1 500 000", "1,5" va "12.50" kabi yozuvlarni tushunadi; xato bo'lsa 0.
    """
    if value is None:
        return 0.0
    text = str(value).replace('\u00a0', '').replace(' ', '')
    if re.fullmatch(r'\d{1,3}([,.]\d{3}){2,}', text):
        # 1,500,000 yoki 1.500.000 - minglik ajratgichlar
        text = re.sub(r'[,.]', '', text)
    text = text.replace(',', '.')
    try:
        number = float(text)
    except ValueError:
        return 0.0
    return number if number > 0 else 0.0


def shop_staff_ids(shop):
    """Do'kon jamoasining (egasi va xodimlar) Telegram ID lari."""
    from .models import AllowedAdmin

    ids = set(AllowedAdmin.objects.filter(shop=shop).values_list('telegram_id', flat=True))
    if shop.owner.username.isdigit():
        ids.add(int(shop.owner.username))
    return ids
