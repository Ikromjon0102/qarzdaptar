# QarzDaptar

Do'konlar uchun **nasiya (qarz) daftari** — Telegram Mini App ko'rinishida ishlaydigan SaaS.
Sotuvchi nasiyani yozadi, mijoz uni Telegram botda ko'radi va tasdiqlaydi, qarz va to'lovlar
avtomatik hisoblanadi.

- Backend: **Django 6** (Python 3.12+), SQLite (PostgreSQL ham qo'llab-quvvatlanadi)
- Frontend: Bootstrap 5 + Telegram Web App (mobil ilova uslubida), landing — Tailwind
- Bot: Telegram Bot API (webhook)
- To'lov: Payme, Click (obuna uchun, ixtiyoriy)

---

## Imkoniyatlar

### Ro'yxatdan o'tish
- Faqat botda: landing'dagi tugma `t.me/<bot>?start=signup` ni ochadi, bot do'kon nomi va
  turini (oziq-ovqat, qurilish, santexnika, maishiy texnika...) so'raydi — do'kon tayyor.
  Telegram ID qo'lda kiritilmaydi. Bekor qilish: `/cancel`.

### Do'kon egasi va xodimlar
- **Savdo**: nasiya yoki naqd; bir nechta tovar, so'm va dollar, kurs bo'yicha jami.
- **To'lov muddati**: nasiyaga muddat (1 hafta / 2 hafta / 1 oy / sana); muddati o'tganlar ro'yxati,
  mijozga ertaga va muddat kuni eslatma. To'lovlar eng eski nasiyani birinchi yopadi (`core/dues.py`).
- **To'lov olish**: mijozning joriy qarzi, «Hammasi» tugmasi, qoldiq oldindan ko'rinadi.
- **Mijozlar**: qidiruv, filtrlar (qarzdorlar, kutilayotgan, botga ulanmagan), mijoz sahifasi
  va operatsiyalar tarixi.
- **Hisobot**: umumiy va oylik; naqd savdo nasiyadan alohida; **Excel'ga eksport**.
- **Xabar yuborish**: hammaga / qarzdorlarga / tanlangan mijozlarga, `{ism}` va `{qarz}` bilan.
- **Avtomatik eslatma**: qarzdorlarga har N kunda botdan eslatma.
- **Onlayn do'kon**: mahsulotlar, mijoz buyurtma beradi, qabul qilinsa nasiyaga yoziladi.
- **Xodimlar**: taklif havolasi orqali qo'shiladi; xodim rahbar bo'limlariga kira olmaydi.

### Mijoz (Telegram orqali)
- Do'kondan kelgan havola orqali botga ulanadi.
- Har bir nasiyani ko'radi va **tasdiqlaydi yoki rad etadi** (sababi bilan).
- Kabinet: joriy qarz, tarix, bir nechta do'kondagi hisoblar, onlayn buyurtma.

### Tariflar (`core/plans.py`)
| | Bepul | Standart | Biznes |
|---|---|---|---|
| Narx (oy / yil) | 0 | 39 000 / 390 000 (ishga tushirish: 29 000 / 290 000) | 79 000 / 790 000 |
| Mijozlar | 30 tagacha | cheksiz | cheksiz |
| Xodimlar | — | 2 tagacha | cheksiz |
| Eslatma, xabar yuborish, Excel | — | ✅ | ✅ |
| Onlayn do'kon | — | — | ✅ |

- Yangi do'kon 14 kun Standart imkoniyatlari bilan ishlaydi, keyin to'lamasa Bepul'ga tushadi.
- Pullik muddat tugasa hech narsa bloklanmaydi va o'chmaydi — faqat cheklovlar qaytadi.
- `subscription_ends_at` bo'sh bo'lsa, tarif muddatsiz (bir umrlik litsenziya uchun).

### Platforma egasi
- `/super-control/` — barcha do'konlar, tarif va muddati; tarifni yoqish (+30 kun / +1 yil).
- To'lov: Payme/Click orqali avtomatik yoki admin orqali qo'lda.

---

## Tezkor ishga tushirish (lokal)

```bash
git clone https://github.com/Ikromjon0102/qarzdaptar.git
cd qarzdaptar
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r req.txt

cp .env.example .env          # kamida BOT_TOKEN ni yozing
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Brauzerda: `http://127.0.0.1:8000/` — landing, `/admin/` — Django admin.

> Ilovaning asosiy qismi **Telegram ichida** ishlaydi (kirish Telegram imzosi orqali).
> Lokal sinash uchun botga HTTPS manzil kerak — masalan `ngrok http 8000`, so'ng `.env` da
> `SITE_DOMAIN` ni o'sha domenga qo'yib, `python manage.py set_webhook` ni bajaring.

Serverga o'rnatish, yangilash, zaxira, Payme/Click sozlash — **[DEPLOY.md](DEPLOY.md)**.

---

## Sozlamalar (`.env`)

Barcha maxfiy va o'zgaruvchan qiymatlar `.env` faylida (namuna: [`.env.example`](.env.example)).
Kodga tegmasdan domen, bot yoki narxni almashtirish mumkin.

| Kalit | Vazifasi |
|---|---|
| `BOT_TOKEN` | @BotFather bergan token |
| `DJANGO_SECRET_KEY` | Django maxfiy kaliti |
| `DJANGO_DEBUG` | Productionda `False` |
| `SITE_DOMAIN`, `ALLOWED_HOSTS` | Sayt domeni |
| `BOT_USERNAME`, `SUPPORT_USERNAME` | Bot va yordam akkaunti (`@` siz) |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook'ni soxta so'rovlardan himoyalash |
| `PLAN_STANDARD_PRICE`, `PLAN_BUSINESS_PRICE` | Tariflar narxi (so'm/oy; yillik = 10 oylik) |
| `PLAN_STANDARD_LAUNCH_PRICE`, `LAUNCH_PRICE_UNTIL`, `LAUNCH_PRICE_LOCK` | Ishga tushirish narxi, oxirgi kuni va to'laganlar uchun saqlanishi |
| `PAYME_*`, `CLICK_*` | Onlayn to'lov (bo'sh bo'lsa o'chiq) |

Sozlanmagan narsa bo'lsa, `python manage.py check` ogohlantiradi.

---

## Boshqaruv buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `python manage.py set_webhook` | Telegram webhook'ini `SITE_DOMAIN` ga o'rnatadi |
| `python manage.py send_reminders [--dry-run]` | Muddat eslatmalari (ertaga / bugun) va qarzdorlarga eslatma (cron, kuniga 1 marta) |
| `python manage.py backup_db [--media]` | Baza (va rasmlar) zaxirasi, eskilarini o'chiradi |
| `python manage.py mark_cash_sales` | Eski naqd savdolarni belgilash (yangilashda 1 marta) |

---

## Loyiha tuzilishi

```
config/        Django sozlamalari, URL lar (.env shu yerda o'qiladi)
core/          Asosiy ilova: do'kon, mijoz, nasiya/to'lov, bot, hisobotlar
  bot_signup.py    Botda do'kon ochish (nomi -> turi)
  landing.py       Landing va maxfiylik sahifasi matnlari (UZ/RU)
  telegram.py      Telegram API (timeout, fonda yuborish)
  telegram_auth.py Mini App initData imzosini tekshirish
  reminders.py     Qarz eslatmalari
  exports.py       Excel hisobotlar
  permissions.py   Rahbar / xodim huquqlari
store/         Onlayn do'kon: mahsulotlar, savat, buyurtmalar
billing/       Obuna to'lovlari: Payme Merchant API, Click SHOP API
templates/     Sahifalar (base.html — umumiy dizayn va tab-bar)
static/        Rasmlar, landing uchun build qilingan CSS
DEPLOY.md      Serverga o'rnatish qo'llanmasi
```

---

## Testlar

```bash
python manage.py test core billing
```

Login va imzo tekshiruvi, rollar, savdo/to'lov, naqd savdo statistikasi, do'kon buyurtmalari,
eslatmalar, Excel, zaxira, Payme va Click protokollari testlar bilan qamrab olingan.

---

## Landing sahifa dizayni

Landing o'zbek va rus tilida (`?lang=ru`). Matnlar shablonda emas, `core/landing.py` da —
matnni o'zgartirish uchun CSS'ni qayta build qilish shart emas.
Ilova skrinshotlari: `static/images/screens/`, ulashish kartochkasi: `static/images/og.png`.

`static/css/landing.css` oldindan build qilingan (serverda Node.js kerak emas).
`templates/landing.html`, `templates/landing/` yoki `templates/privacy.html` dagi klasslarni o'zgartirsangiz:

```bash
npm install
npm run build:css
```

---

## Aloqa

Savollar va obuna: Telegram — [@ergashev_ikromjon](https://t.me/ergashev_ikromjon)
