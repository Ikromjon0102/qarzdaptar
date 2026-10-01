#!/usr/bin/env bash
# QarzDaptar - serverga deploy / yangilash.
#
#   bash server_deploy.sh               # yangilash: kod, kutubxonalar, migratsiya (baza saqlanadi)
#   bash server_deploy.sh --fresh-db    # BIRINCHI deploy: eski baza nusxaga olinib, toza baza yaratiladi
#
# Faqat /root/qarzdaptar va gunicorn-qarzdaptar servisiga tegadi.
# Nginx va boshqa loyihalar o'zgartirilmaydi.
set -euo pipefail

APP_DIR="${APP_DIR:-/root/qarzdaptar}"
BRANCH="${BRANCH:-claude/ux-ui-analysis-user-flow-ky4rc5}"
SERVICE="${SERVICE:-gunicorn-qarzdaptar}"
PORT="${PORT:-8001}"
DOMAIN="${DOMAIN:-qarzdaptar.uz}"
BOT_USERNAME="${BOT_USERNAME:-QarzDaptarBot}"
BACKUP_ROOT="${BACKUP_ROOT:-/root/deploy-backups}"

FRESH_DB=0
[[ "${1:-}" == "--fresh-db" ]] && FRESH_DB=1

TS="$(date +%Y%m%d-%H%M%S)"
BK="$BACKUP_ROOT/qarzdaptar-$TS"

step() { echo; echo "=== $* ==="; }
die()  { echo "❌ $*" >&2; exit 1; }

# --- 0. Tekshiruvlar ---------------------------------------------------------
step "0. Tekshiruv"
[[ $EUID -eq 0 ]] || die "root sifatida ishga tushiring"
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR git repo emas"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || die "Python 3.12+ kerak (Django 6). Hozirgi: $(python3 --version)"
python3 -m venv --help >/dev/null 2>&1 || die "python3-venv o'rnatilmagan: apt install python3-venv"
echo "Papka: $APP_DIR | branch: $BRANCH | servis: $SERVICE (port $PORT) | domen: $DOMAIN"
[[ $FRESH_DB -eq 1 ]] && echo "⚠️  --fresh-db: eski baza nusxaga olinadi va TOZA baza yaratiladi"

# --- 1. Zaxira nusxa (hech narsa o'zgartirilmasdan oldin) --------------------
step "1. Zaxira: $BK"
mkdir -p "$BK"
systemctl cat "$SERVICE" > "$BK/$SERVICE.service" 2>/dev/null || true
tar czf "$BK/qarzdaptar.tar.gz" -C "$(dirname "$APP_DIR")" \
    --exclude="$(basename "$APP_DIR")/venv" --exclude="$(basename "$APP_DIR")/node_modules" \
    "$(basename "$APP_DIR")"
(cd "$APP_DIR" && git rev-parse HEAD > "$BK/git-head.txt" && git diff > "$BK/local-changes.diff" || true)
cat > "$BK/rollback.sh" <<ROLLBACK
#!/usr/bin/env bash
# Eski versiyaga qaytish (shu zaxira nusxadan)
set -e
systemctl stop $SERVICE || true
rm -rf "$APP_DIR"
tar xzf "$BK/qarzdaptar.tar.gz" -C "$(dirname "$APP_DIR")"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/req.txt" gunicorn
systemctl start $SERVICE
echo "Eski versiya tiklandi. Webhook'ni eski holatga qaytarish kerak bo'lsa - qo'lda o'rnating."
ROLLBACK
chmod +x "$BK/rollback.sh"
echo "✅ Zaxira tayyor ($(du -sh "$BK" | cut -f1)). Qaytish: bash $BK/rollback.sh"

# --- 2. Yangi kodni olish (GitHub) -------------------------------------------
step "2. GitHub'dan $BRANCH"
cd "$APP_DIR"
git fetch origin "$BRANCH" || die "git fetch muvaffaqiyatsiz (GitHub login/token kerak bo'lishi mumkin). Hech narsa o'zgartirilmadi."

# --- 3. Servisni to'xtatib, kodni almashtirish -------------------------------
step "3. Kodni yangilash"
systemctl stop "$SERVICE"
git checkout -f -B "$BRANCH" "origin/$BRANCH"
# Eski, repoda bo'lmagan fayllarni tozalash (eski migratsiyalar, staticfiles, db1.sqlite3 ...).
# Saqlanadi: .env, media, logs, backups, venv (va --fresh-db bo'lmasa - db.sqlite3)
# (db.sqlite3 bu yerda o'chirilmaydi: --fresh-db da 6-qadamda zaxira papkasiga ko'chiriladi)
git clean -fdx -e .env -e media -e logs -e backups -e venv -e db.sqlite3
echo "Kod: $(git log --oneline -1)"

# --- 4. Virtual muhit va kutubxonalar ----------------------------------------
step "4. Kutubxonalar (venv)"
python3 -m venv --clear venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r req.txt
venv/bin/python -c "import django, gunicorn; print('Django', django.get_version(), '| gunicorn', gunicorn.__version__)"

# --- 5. .env (birinchi marta yaratiladi, keyin saqlanadi) --------------------
step "5. .env"
if [[ ! -f .env ]]; then
    read -rsp "Yangi BOT_TOKEN ni kiriting (@$BOT_USERNAME): " BOT_TOKEN; echo
    [[ "$BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || die "Token formati noto'g'ri"
    SECRET="$(venv/bin/python -c 'from django.core.management.utils import get_random_secret_key as g; print(g())')"
    HOOK="$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    umask 077
    cat > .env <<ENV
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=False
BOT_TOKEN=$BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET=$HOOK
SITE_DOMAIN=$DOMAIN
BOT_USERNAME=$BOT_USERNAME
SUPPORT_USERNAME=ergashev_ikromjon
ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN
SUBSCRIPTION_PRICE=100000
ENV
    umask 022
    echo "✅ .env yaratildi (ruxsat 600)"
else
    echo "Mavjud .env saqlandi"
fi

# --- 6. Baza va statik fayllar -----------------------------------------------
step "6. Baza va statik fayllar"
if [[ $FRESH_DB -eq 1 && -f db.sqlite3 ]]; then
    mv db.sqlite3 "$BK/db.sqlite3.old"   # nusxa zaxirada ham bor
    echo "Eski baza: $BK/db.sqlite3.old"
fi
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput -v 0
# Nginx eski "staticfiles/" papkasini kutayotgan bo'lsa ham ishlashi uchun
[[ -e staticfiles ]] || ln -s static-files staticfiles
venv/bin/python manage.py check --deploy 2>&1 | grep -E "core\.W|ERROR" || true

# --- 7. Servisni ishga tushirish ---------------------------------------------
step "7. Servis"
systemctl start "$SERVICE"
sleep 3
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 40 --no-pager; die "Servis ishga tushmadi. Qaytish: bash $BK/rollback.sh"; }
code="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $DOMAIN" "http://127.0.0.1:$PORT/")"
[[ "$code" == "200" ]] || { journalctl -u "$SERVICE" -n 40 --no-pager; die "Sayt $code qaytardi. Qaytish: bash $BK/rollback.sh"; }
# Tashqi tekshiruv - faqat ma'lumot uchun (deploy'ni to'xtatmaydi)
ext="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/" || true)"
static="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/static/css/landing.css" || true)"
echo "✅ Lokal: 200 | https://$DOMAIN: ${ext:-?} | statik fayl: ${static:-?}"

# --- 8. Telegram webhook -----------------------------------------------------
step "8. Telegram webhook"
# Sayt allaqachon ishlayapti - webhook xatosi deploy'ni to'xtatmaydi, faqat ogohlantiradi
venv/bin/python manage.py set_webhook || echo "⚠️  Webhook o'rnatilmadi - BOT_TOKEN ni tekshiring, so'ng: venv/bin/python manage.py set_webhook"
venv/bin/python - 2>/dev/null <<'PY' || echo "⚠️  Telegram'dan bot ma'lumotini olib bo'lmadi"
import json, os, urllib.request
for line in open('.env', encoding='utf-8'):
    if line.startswith('BOT_TOKEN='):
        token = line.strip().split('=', 1)[1]
info = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15))["result"]
me = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=15))["result"]
print(f"Bot: @{me['username']} | webhook: {info.get('url')} | kutilayotgan: {info.get('pending_update_count')}"
      f" | oxirgi xato: {info.get('last_error_message', 'yo`q')}")
PY

# --- 9. Cron (zaxira va eslatmalar) ------------------------------------------
step "9. Cron"
CRON_BACKUP="0 3 * * * cd $APP_DIR && venv/bin/python manage.py backup_db --media >> logs/backup.log 2>&1"
CRON_REMIND="0 10 * * * cd $APP_DIR && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1"
current="$(crontab -l 2>/dev/null || true)"
new="$current"
grep -qF "manage.py backup_db" <<<"$current" || new+=$'\n'"$CRON_BACKUP"
grep -qF "manage.py send_reminders" <<<"$current" || new+=$'\n'"$CRON_REMIND"
if [[ "$new" != "$current" ]]; then
    printf '%s\n' "$new" | sed '/^$/d' | crontab -
    echo "Cron qo'shildi (03:00 zaxira, 10:00 eslatma)"
else
    echo "Cron allaqachon bor"
fi

step "TAYYOR"
echo "Sayt:   https://$DOMAIN"
echo "Bot:    https://t.me/$BOT_USERNAME  ->  /start"
echo "Loglar: tail -f $APP_DIR/logs/qarzdaptar.log   |   journalctl -u $SERVICE -f"
echo "Qaytish (agar kerak bo'lsa): bash $BK/rollback.sh"
echo "Superadmin (/super-control/, /admin/):  cd $APP_DIR && venv/bin/python manage.py createsuperuser"
