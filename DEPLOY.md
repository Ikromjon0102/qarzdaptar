# QarzDaptar — serverga o'rnatish

Talablar: **Python 3.12+** (Django 6.0), `pip`.

## 0. Avtomatik skript (tavsiya etiladi)

`deploy/server_deploy.sh` — zaxira, kodni yangilash, venv, migratsiya, `.env`, servis, webhook va
cron'ni bitta buyruqda bajaradi. Faqat `/root/qarzdaptar` va `gunicorn-qarzdaptar` ga tegadi
(nginx va boshqa loyihalar o'zgarmaydi). Har safar `deploy-backups/` ga to'liq nusxa va
`rollback.sh` yoziladi.

```bash
cd /root/qarzdaptar
git fetch origin claude/ux-ui-analysis-user-flow-ky4rc5
git show FETCH_HEAD:deploy/server_deploy.sh > /root/server_deploy.sh
bash /root/server_deploy.sh --fresh-db   # birinchi marta: toza baza (eski baza zaxirada qoladi)
bash /root/server_deploy.sh              # keyingi yangilanishlar: baza saqlanadi
```

Sozlash uchun muhit o'zgaruvchilari: `APP_DIR`, `BRANCH`, `SERVICE`, `PORT`, `DOMAIN`, `BOT_USERNAME`.

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

**Qo'lda (har doim ishlaydi):** to'lov admin bilan Telegram orqali kelishiladi. Pul tushgach
`/super-control/` → do'kon yonidagi **«+30 kun»**.

**Avtomatik — Payme va Click** (kalitlar `.env` da bo'lmasa, tugmalar ko'rinmaydi):

*Payme* ([business.paycom.uz](https://business.paycom.uz)):
1. Kassa yarating, turi — **«Merchant API»**.
2. Kassa sozlamalarida **Endpoint URL**: `https://<SITE_DOMAIN>/billing/payme/`
3. **Hisob (account) maydoni**: `order_id` (turi: raqam).
4. `.env`: `PAYME_MERCHANT_ID` (kassa ID), `PAYME_KEY` (kalit). Avval test kassasi bilan:
   `PAYME_TEST_MODE=True` va test kalitini yozing, [test.paycom.uz](https://test.paycom.uz) da
   barcha stsenariylarni o'tkazing, keyin haqiqiy kalitga almashtiring.

*Click* ([merchant.click.uz](https://merchant.click.uz)):
1. Servis yarating, **Prepare URL** va **Complete URL** — ikkalasiga ham:
   `https://<SITE_DOMAIN>/billing/click/`
2. `.env`: `CLICK_SERVICE_ID`, `CLICK_MERCHANT_ID`, `CLICK_SECRET_KEY`.

To'lov o'tgach obuna avtomatik uzaytiriladi (1/3/6 oy) va do'kon egasiga Telegram'da xabar keladi.
Barcha to'lovlar: `/admin/` → **Obuna to'lovlari**. Muvaffaqiyatli Payme to'lovini bekor qilish
so'ralsa, tizim rad etadi (-31007) — pulni qaytarish Payme kabineti va admin orqali qo'lda qilinadi.

## 6. Landing sahifa dizayni (Tailwind)

`static/css/landing.css` oldindan build qilingan va repoda turadi — serverda Node.js kerak emas.
Faqat `templates/landing.html` dagi klasslarni o'zgartirsangiz, qayta build qiling:

```bash
npm install
npm run build:css
```

## 7. Zaxira nusxa (backup) — albatta sozlang

```bash
python manage.py backup_db --media        # backups/ ga; oxirgi 14 ta nusxa saqlanadi
```

Har kuni avtomatik (`crontab -e`):

```
0 3 * * * cd /path/to/qarzdaptar && venv/bin/python manage.py backup_db --media >> logs/backup.log 2>&1
```

Nusxalarni **boshqa joyga** ham ko'chirib turing (server diski buzilsa, u yerdagi nusxa ham yo'qoladi):
`BACKUP_DIR=/mnt/disk2/backups` yoki `rclone`/`scp` bilan tashqi xotiraga.

**Tiklash:** serverni to'xtating, so'ng

```bash
cp db.sqlite3 db.sqlite3.broken
gunzip -c backups/db-YYYYMMDD-HHMMSS.sqlite3.gz > db.sqlite3
tar xzf backups/media-YYYYMMDD-HHMMSS.tar.gz        # media/ ni tiklaydi
```

## 8. Qarzdorlarga avtomatik eslatma

Do'kon rahbari **Sozlamalar → Qarzdorlarga eslatma** da yoqadi (necha kunda bir, eng kam summa).
Yuborishni cron bajaradi (kuniga bir marta):

```
0 10 * * * cd /path/to/qarzdaptar && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
```

Kimga borishini oldindan ko'rish: `python manage.py send_reminders --dry-run`

## 9. Loglar

Xatolar `logs/qarzdaptar.log` ga yoziladi (5 MB dan oshsa yangi faylga o'tadi, 5 ta saqlanadi).
Telegram'ga xabar ketmasa, avval shu faylni ko'ring: `tail -n 50 logs/qarzdaptar.log`

## 10. Tekshirish

```bash
python manage.py test core billing   # avtomatik testlar
python manage.py check          # sozlamalar
```
