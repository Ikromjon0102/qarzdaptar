import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """
    .env faylidagi KEY=VALUE qatorlarini muhit o'zgaruvchilariga yuklaydi
    (serverda haqiqiy muhit o'zgaruvchilari ustun turadi).
    """
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_list(name, default=''):
    # Bo'sh qiymat ham "berilmagan" deb hisoblanadi
    return [item.strip() for item in (os.environ.get(name) or default).split(',') if item.strip()]


_load_env_file(BASE_DIR / '.env')

# --- Maxfiy qiymatlar: faqat .env yoki muhit o'zgaruvchilaridan (repoga yozilmaydi) ---
# Namuna: .env.example
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or 'django-insecure-dev-only-change-me'
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
# Telegram xabarlari fonda yuboriladi (testlarda - sinxron, natijani tekshirish uchun)
TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'
TELEGRAM_ASYNC = not TESTING
# Telegram webhook'ga yuboradigan maxfiy kalit (setWebhook secret_token). Bo'sh bo'lsa tekshirilmaydi.
TELEGRAM_WEBHOOK_SECRET = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')

# --- Sayt va bot sozlamalari ---
SITE_DOMAIN = os.environ.get('SITE_DOMAIN') or 'telapp.tunl.uz'
BASE_URL = f'https://{SITE_DOMAIN}'
BOT_USERNAME = os.environ.get('BOT_USERNAME') or 'QarzDaptarBot'
SUPPORT_USERNAME = os.environ.get('SUPPORT_USERNAME') or 'ergashev_ikromjon'
# Oylik obuna narxi (so'm) - obuna sahifasida ko'rsatiladi
SUBSCRIPTION_PRICE = int(os.environ.get('SUBSCRIPTION_PRICE') or 100000)

# --- Obuna to'lovi: Payme va Click (kalitlar berilmasa - tugmalar ko'rinmaydi, faqat qo'lda to'lov) ---
PAYME_MERCHANT_ID = os.environ.get('PAYME_MERCHANT_ID', '')
PAYME_KEY = os.environ.get('PAYME_KEY', '')
PAYME_TEST_MODE = (os.environ.get('PAYME_TEST_MODE') or 'False').lower() in ('1', 'true', 'yes')
CLICK_SERVICE_ID = os.environ.get('CLICK_SERVICE_ID', '')
CLICK_MERCHANT_ID = os.environ.get('CLICK_MERCHANT_ID', '')
CLICK_SECRET_KEY = os.environ.get('CLICK_SECRET_KEY', '')

# Standart qiymatlar avvalgidek (server buzilmasligi uchun); productionda .env da aniq domen yozing
ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS', '*')
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS',
                                 f'https://{SITE_DOMAIN},https://qarzdaptar.uz,https://*.tunl.uz')

# Telegram Web (web.telegram.org) Mini App'ni iframe ichida ochadi
X_FRAME_OPTIONS = 'ALLOWALL'


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'core',
    'store',
    'billing',


]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # statik fayllar (DEBUG=False da ham)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'core.middleware.SubscriptionMiddleware', #check subs
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.shop_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'qarzdaptar_db',
#         'USER': 'qarzdaptar_user',
#         'PASSWORD': 'qarzdaptar',
#         'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Tashkent'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static-files')
STATICFILES_DIRS = [BASE_DIR / 'static']

# Statik fayllarni WhiteNoise beradi (nginx sozlash shart emas).
# USE_FINDERS: `collectstatic` qilinmagan bo'lsa ham fayllar topiladi.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
WHITENOISE_USE_FINDERS = True

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Yuklangan fayllarni (mahsulot rasmlari) Django o'zi beradi. Nginx beradigan bo'lsa: SERVE_MEDIA=False
SERVE_MEDIA = (os.environ.get('SERVE_MEDIA') or 'True').lower() in ('1', 'true', 'yes')



# settings.py oxiriga qo'shing:
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ' '


# --- LOGLAR ---
# Xatolar konsolga va logs/qarzdaptar.log ga yoziladi (5 MB dan oshsa aylanadi, 5 ta fayl saqlanadi)
LOG_DIR = Path(os.environ.get('LOG_DIR') or BASE_DIR / 'logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{asctime} {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'qarzdaptar.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'simple',
            'encoding': 'utf-8',
        },
    },
    'root': {'handlers': ['console', 'file'], 'level': 'WARNING'},
    'loggers': {
        'core': {'level': 'INFO'},
        'store': {'level': 'INFO'},
        'django.request': {'level': 'ERROR'},
    },
}
