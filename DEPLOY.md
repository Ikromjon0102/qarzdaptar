# QarzDaptar — serverga o'rnatish

Talablar: **Python 3.12+** (Django 6.0), `pip`.

## 1. Birinchi marta o'rnatish (yangi server)

```bash
git clone <repo> && cd qarzdaptar
python -m venv venv && source venv/bin/activate
pip install -r req.txt

cp .env.example .env        # va qiymatlarni to'ldiring (pastga qarang)
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser   # platforma admini (/admin/)
python manage.py set_webhook       # Telegram webhook'ini o'rnatadi
python manage.py check             # sozlanmagan narsa bo'lsa aytadi
```

## 2. Mavjud serverni yangilash

> ⚠️ Avval bazaning nusxasini oling: `cp db.sqlite3 db.sqlite3.bak`

Migratsiya fayllari endi repoda. Serverda avval `makemigrations` bilan yaratilgan
**eski migratsiya fayllari** `git pull` ga xalaqit beradi, ularni o'chiring
(bazadagi ma'lumotlarga tegmaydi):

```bash
cp db.sqlite3 db.sqlite3.bak
rm -f core/migrations/0*.py store/migrations/0*.py
git pull
pip install -r req.txt              # whitenoise qo'shildi

cp .env.example .env                # birinchi marta; qiymatlarni to'ldiring
python manage.py migrate --fake-initial
python manage.py mark_cash_sales    # eski naqd savdolarni belgilaydi (bir marta)
python manage.py collectstatic --noinput
python manage.py set_webhook
python manage.py check
```

`--fake-initial`: jadvallar allaqachon bor bo'lsa, boshlang'ich migratsiyani
"bajarilgan" deb belgilaydi va faqat yangi o'zgarishlarni (`core 0002`) qo'llaydi.

Keyin serverni (gunicorn / uwsgi / runserver) qayta ishga tushiring.

## 3. `.env` qiymatlari

| Kalit | Nima | Misol |
|---|---|---|
| `BOT_TOKEN` | @BotFather bergan token | `123456:ABC...` |
| `DJANGO_SECRET_KEY` | Tasodifiy uzun kalit | `.env.example` da yaratish buyrug'i bor |
| `DJANGO_DEBUG` | Productionda `False` | `False` |
| `SITE_DOMAIN` | Sayt domeni (`https://` siz) | `qarzdaptar.uz` |
| `BOT_USERNAME` | Bot nomi (`@` siz) | `QarzDaptarBot` |
| `SUPPORT_USERNAME` | Obuna to'lovi uchun Telegram akkaunt | `ergashev_ikromjon` |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook maxfiy kaliti (A-Z a-z 0-9 _ -) | `k3J9_x...` |
| `ALLOWED_HOSTS` | Vergul bilan domenlar | `qarzdaptar.uz,www.qarzdaptar.uz` |
| `SUBSCRIPTION_PRICE` | Oylik obuna narxi (so'm) | `100000` |
| `SERVE_MEDIA` | Rasmlarni Django bersinmi (nginx bersa `False`) | `True` |

**Domen yoki bot almashsa:** faqat `.env` ni o'zgartiring, serverni qayta ishga
tushiring va `python manage.py set_webhook` ni bajaring. Kodga tegish shart emas.

## 4. Statik va media fayllar

- Statik fayllar (CSS, rasmlar) — **WhiteNoise** beradi, `DEBUG=False` da ham ishlaydi.
- Yuklangan rasmlar (`media/`) — `SERVE_MEDIA=True` bo'lsa Django beradi.
  Trafik oshsa, nginx'da `/media/` ni to'g'ridan-to'g'ri berib, `SERVE_MEDIA=False` qiling.

## 5. Obuna to'lovini qabul qilish

To'lov admin bilan Telegram orqali kelishiladi. Pul tushgach: `/admin/` → **Shops** →
do'konni belgilang → **Action: «Obunani 30 kunga uzaytirish»** → Go.

## 6. Landing sahifa dizayni (Tailwind)

`static/css/landing.css` oldindan build qilingan va repoda turadi — serverda Node.js kerak emas.
Faqat `templates/landing.html` dagi klasslarni o'zgartirsangiz, qayta build qiling:

```bash
npm install
npm run build:css
```

## 7. Tekshirish

```bash
python manage.py test core      # avtomatik testlar
python manage.py check          # sozlamalar
```
