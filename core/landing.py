"""
Landing sahifa va maxfiylik siyosati: matnlar (o'zbekcha / ruscha) va ko'rinishlar.

Til: ?lang=ru yoki ?lang=uz (cookie'da eslab qolinadi), aks holda o'zbekcha.
Matnlar shu yerda - shablonga tegmasdan tahrirlash mumkin.
"""
from django.conf import settings
from django.shortcuts import render

from .bot_signup import CATEGORY_EMOJI, TRIAL_DAYS
from .models import Shop

LANGS = ('uz', 'ru')
LANG_COOKIE = 'site_lang'

# Lucide uslubidagi ikonkalar (24x24, chiziqli). Shablonda: <svg ...>{{ icon|safe }}</svg>
ICONS = {
    'shield': '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    'bell': '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    'send': '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    'chart': '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    'coins': '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
    'users': '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    'store': '<path d="M3 9h18l-1.5-5h-15z"/><path d="M5 9v11h14V9"/><path d="M10 20v-5h4v5"/>',
    'cash': '<rect width="20" height="12" x="2" y="6" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
    'book': '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="m14.5 7-5 5"/><path d="m9.5 7 5 5"/>',
    'dispute': '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'calculator': '<rect width="16" height="20" x="4" y="2" rx="2"/><path d="M8 6h8M16 14v4M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'arrow': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    'wallet': '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
}

CATEGORY_RU = {
    'grocery': 'Продукты', 'construction': 'Стройматериалы', 'plumbing': 'Сантехника',
    'tech': 'Бытовая техника', 'electronics': 'Телефоны и электроника', 'clothing': 'Одежда',
    'household': 'Хозтовары', 'auto': 'Автозапчасти', 'pharmacy': 'Аптека',
    'cosmetics': 'Косметика и парфюмерия', 'furniture': 'Мебель', 'other': 'Другое',
}

TEXT = {
    'uz': {
        'title': "QarzDaptar — nasiya daftari Telegramda",
        'description': "Do'kon uchun nasiya daftari: mijoz har bir nasiyani Telegramda o'zi tasdiqlaydi, "
                       "qarzdorlarga eslatma avtomatik boradi. {trial} kun bepul.",
        'nav': [('#features', 'Imkoniyatlar'), ('#pricing', 'Narx'), ('#faq', 'Savollar')],
        'cta': "Telegram orqali boshlash",
        'cta_short': "Boshlash",
        'badge': "Telegram ichida ishlaydi · {trial} kun bepul",
        'hero_title': "Nasiya daftaringiz endi Telegramda",
        'hero_accent': "Mijoz har bir yozuvni o'zi tasdiqlaydi.",
        'hero_text': "Nasiyani yozasiz — mijozga Telegramda xabar boradi, u tasdiqlaydi va qarz hisobga yoziladi. "
                     "«Men buni olmaganman» degan tortishuvlar tugaydi.",
        'hero_secondary': "Qanday ishlaydi?",
        'hero_note': "Ilova o'rnatish shart emas · Karta talab qilinmaydi · 1 daqiqada tayyor",
        'float_confirm': "Nodira nasiyani tasdiqladi",
        'float_amount': "275 000 so'm",
        'float_remind': "Eslatma yuborildi: 3 ta qarzdor",
        'problems_kicker': "Muammo va yechim",
        'problems_title': "Qog'oz daftarning har bir muammosiga javob",
        'problems': [
            ('book', "Daftar yo'qoladi, yirtiladi, ho'l bo'ladi",
             "Ma'lumotlar serverda saqlanadi, har kuni zaxira nusxa olinadi. Telefon almashsa ham hammasi joyida."),
            ('dispute', "Mijoz «men buni olmaganman» deydi",
             "Har bir nasiyani mijoz o'z Telegramida tasdiqlaydi. Tasdiqlanmagan yozuv qarzga qo'shilmaydi."),
            ('bell', "Qarzni so'rash noqulay",
             "Bot qarzdorlarga o'zi muloyim eslatma yuboradi — siz belgilagan kunlarda."),
            ('calculator', "Hisob-kitobga soatlab vaqt ketadi",
             "Jami qarz, bugungi savdo va oylik hisobot bir zumda tayyor. Excel'ga ham chiqariladi."),
        ],
        'how_kicker': "Qanday ishlaydi",
        'how_title': "Uch qadam — va daftar kerak emas",
        'steps': [
            ("Botda do'kon oching",
             "@{bot} ga kiring, do'kon nomini yozing va turini tanlang. Bir daqiqa ham ketmaydi."),
            ("Mijozni qo'shing",
             "Ism va telefonini yozing, so'ng unga havola yuboring — mijoz bir bosishda botga ulanadi."),
            ("Nasiya yozing",
             "Tovar va narxni kiriting. Mijozga Telegramda xabar boradi, u tasdiqlagach qarz hisobga yoziladi."),
        ],
        'screens': [
            ('app-home', "Bosh sahifa: jami qarz va so'nggi amallar"),
            ('app-sale', "Nasiya yozish: tovarlar, so'm va dollar"),
            ('app-confirm', "Mijoz ekrani: tasdiqlash yoki rad etish"),
        ],
        'features_kicker': "Imkoniyatlar",
        'features_title': "Do'kon uchun kerakli hamma narsa",
        'features': [
            ('shield', "Mijoz tasdiqlaydi", "Har bir nasiya mijozning roziligi bilan. Rad etsa — sababini ko'rasiz."),
            ('bell', "Avtomatik eslatma", "Qarzdorlarga har N kunda botdan eslatma boradi."),
            ('send', "Xabar yuborish", "Hammaga, faqat qarzdorlarga yoki tanlangan mijozlarga — ism va qarzi bilan."),
            ('chart', "Hisobot va Excel", "Kunlik va oylik natija, eng katta qarzdorlar, Excel'ga eksport."),
            ('coins', "So'm va dollar", "Har bir tovar o'z valyutasida, kurs sozlamalarda."),
            ('users', "Xodimlar", "Sotuvchilarni havola orqali qo'shing. O'chirish va sozlamalar faqat sizda."),
            ('store', "Onlayn do'kon", "Mijoz Telegramdan buyurtma beradi, qabul qilsangiz nasiyaga yoziladi."),
            ('cash', "Naqd savdo", "Naqd savdolar ham hisobda, lekin qarzga aralashmaydi."),
        ],
        'types_title': "Har qanday do'kon uchun",
        'pricing_kicker': "Narx",
        'pricing_title': "Oddiy va tushunarli",
        'trial_label': "{trial} kun bepul",
        'trial_text': "Barcha imkoniyatlar ochiq. Karta talab qilinmaydi.",
        'per_month': "so'm / oy",
        'after_trial': "sinov muddatidan keyin",
        'included': ["Cheksiz mijozlar va nasiyalar", "Xodimlar va ruxsatlar", "Avtomatik eslatmalar",
                     "Hisobot va Excel eksport", "Onlayn do'kon", "Har kuni zaxira nusxa"],
        'pricing_note': "To'lamasangiz ham ma'lumotlaringiz o'chmaydi.",
        'faq_title': "Ko'p beriladigan savollar",
        'faq': [
            ("Mijozda Telegram bo'lmasa-chi?",
             "Nasiyani baribir yozasiz. Mijoz o'zi tasdiqlay olmagani uchun yozuvni siz (rahbar) tasdiqlaysiz. "
             "Keyinroq mijozga havola yuborsangiz, u ham botga ulanadi."),
            ("Ma'lumotlarim xavfsizmi?",
             "Ma'lumotlar serverda saqlanadi va har kuni zaxira nusxa olinadi. Do'kon ma'lumotlarini faqat siz va "
             "xodimlaringiz ko'radi, mijoz esa faqat o'z hisobini."),
            ("Telefonim yo'qolsa yoki almashsa?",
             "Hech narsa yo'qolmaydi. Yangi telefonda Telegramga kiring va botni oching — hammasi joyida."),
            ("Xodim qo'shsam bo'ladimi?",
             "Ha. Xodimga taklif havolasini yuborasiz. U savdo va to'lov yoza oladi, lekin yozuvni o'chirish va "
             "sozlamalar faqat rahbarda."),
            ("Dollarda savdo qilsam-chi?",
             "Har bir tovarni so'm yoki dollarda yozish mumkin. Qarz ikkala valyutada alohida hisoblanadi."),
            ("Sinov muddati tugagach nima bo'ladi?",
             "Oylik to'lovni qilsangiz, davom etasiz. To'lamasangiz ham ma'lumotlar o'chmaydi — to'lovdan keyin "
             "hammasi qaytadi."),
        ],
        'final_title': "Daftarni bugun yopib qo'ying",
        'final_text': "Bir daqiqada do'kon oching — {trial} kun bepul.",
        'footer_contact': "Aloqa",
        'footer_privacy': "Maxfiylik siyosati",
        'footer_rights': "Barcha huquqlar himoyalangan.",
        'screens_alt': "QarzDaptar ilovasi ekrani",
        'privacy_title': "Maxfiylik siyosati",
        'privacy_back': "Bosh sahifa",
        'privacy': [
            ("Qanday ma'lumotlar saqlanadi",
             "Do'kon nomi va turi, do'kon egasi va xodimlarning Telegram ID raqami va ismi, mijozlarning ismi, "
             "telefon raqami va Telegram ID raqami, nasiya va to'lov yozuvlari."),
            ("Nima uchun ishlatiladi",
             "Faqat xizmatni ko'rsatish uchun: nasiya va to'lovlarni hisoblash, mijozga tasdiqlash so'rovi va "
             "eslatma yuborish, hisobotlar tayyorlash."),
            ("Kim ko'radi",
             "Do'kon ma'lumotlarini faqat do'kon egasi va u qo'shgan xodimlar ko'radi. Mijoz faqat o'z hisobini "
             "ko'radi. Ma'lumotlar uchinchi shaxslarga sotilmaydi va berilmaydi."),
            ("Saqlash va xavfsizlik",
             "Ma'lumotlar serverda saqlanadi, har kuni zaxira nusxa olinadi. Kirish faqat Telegram imzosi orqali."),
            ("O'chirish",
             "Do'kon yoki mijoz ma'lumotlarini o'chirishni so'rash uchun biz bilan Telegram orqali bog'laning."),
        ],
    },
    'ru': {
        'title': "QarzDaptar — тетрадь долгов в Telegram",
        'description': "Учёт продаж в долг для магазина: клиент сам подтверждает каждую запись в Telegram, "
                       "должникам автоматически приходят напоминания. {trial} дней бесплатно.",
        'nav': [('#features', 'Возможности'), ('#pricing', 'Цена'), ('#faq', 'Вопросы')],
        'cta': "Начать в Telegram",
        'cta_short': "Начать",
        'badge': "Работает в Telegram · {trial} дней бесплатно",
        'hero_title': "Тетрадь долгов теперь в Telegram",
        'hero_accent': "Клиент сам подтверждает каждую запись.",
        'hero_text': "Вы записываете долг — клиенту приходит сообщение в Telegram, он подтверждает, и долг "
                     "учитывается. Споры «я этого не брал» больше не возникают.",
        'hero_secondary': "Как это работает?",
        'hero_note': "Без установки приложения · Без карты · Готово за 1 минуту",
        'float_confirm': "Нодира подтвердила долг",
        'float_amount': "275 000 сум",
        'float_remind': "Напоминание отправлено: 3 должника",
        'problems_kicker': "Проблема и решение",
        'problems_title': "Ответ на каждую проблему бумажной тетради",
        'problems': [
            ('book', "Тетрадь теряется, рвётся, намокает",
             "Данные хранятся на сервере, резервная копия делается каждый день. Сменили телефон — всё на месте."),
            ('dispute', "Клиент говорит «я этого не брал»",
             "Каждую запись клиент подтверждает в своём Telegram. Неподтверждённая запись не идёт в долг."),
            ('bell', "Неудобно напоминать о долге",
             "Бот сам вежливо напоминает должникам — в те дни, которые вы выберете."),
            ('calculator', "Подсчёты отнимают часы",
             "Общий долг, продажи за день и отчёт за месяц — мгновенно. Есть выгрузка в Excel."),
        ],
        'how_kicker': "Как это работает",
        'how_title': "Три шага — и тетрадь не нужна",
        'steps': [
            ("Откройте магазин в боте",
             "Зайдите в @{bot}, напишите название магазина и выберите тип. Меньше минуты."),
            ("Добавьте клиента",
             "Укажите имя и телефон, отправьте клиенту ссылку — он подключится к боту в одно касание."),
            ("Запишите долг",
             "Введите товары и цены. Клиенту придёт сообщение в Telegram, после подтверждения долг учитывается."),
        ],
        'screens': [
            ('app-home', "Главная: общий долг и последние операции"),
            ('app-sale', "Новая запись: товары, сумы и доллары"),
            ('app-confirm', "Экран клиента: подтвердить или отклонить"),
        ],
        'features_kicker': "Возможности",
        'features_title': "Всё, что нужно магазину",
        'features': [
            ('shield', "Подтверждение клиентом", "Каждый долг — с согласия клиента. Отклонил — вы видите причину."),
            ('bell', "Автонапоминания", "Должникам каждые N дней приходит напоминание от бота."),
            ('send', "Рассылка", "Всем, только должникам или выбранным клиентам — с именем и суммой долга."),
            ('chart', "Отчёты и Excel", "Итоги дня и месяца, крупнейшие должники, выгрузка в Excel."),
            ('coins', "Сумы и доллары", "Каждый товар в своей валюте, курс задаётся в настройках."),
            ('users', "Сотрудники", "Добавляйте продавцов по ссылке. Удаление и настройки — только у вас."),
            ('store', "Онлайн-магазин", "Клиент заказывает в Telegram, после принятия заказ идёт в долг."),
            ('cash', "Продажи за наличные", "Наличные продажи тоже учитываются, но не смешиваются с долгами."),
        ],
        'types_title': "Для любого магазина",
        'pricing_kicker': "Цена",
        'pricing_title': "Просто и понятно",
        'trial_label': "{trial} дней бесплатно",
        'trial_text': "Все возможности открыты. Карта не нужна.",
        'per_month': "сум / мес",
        'after_trial': "после пробного периода",
        'included': ["Без ограничений по клиентам и записям", "Сотрудники и права доступа", "Автонапоминания",
                     "Отчёты и выгрузка в Excel", "Онлайн-магазин", "Ежедневное резервное копирование"],
        'pricing_note': "Даже без оплаты ваши данные не удаляются.",
        'faq_title': "Частые вопросы",
        'faq': [
            ("А если у клиента нет Telegram?",
             "Долг всё равно записывается. Клиент не может подтвердить его сам, поэтому запись подтверждаете вы "
             "(руководитель). Позже отправите клиенту ссылку — и он тоже подключится."),
            ("Мои данные в безопасности?",
             "Данные хранятся на сервере, резервная копия делается каждый день. Данные магазина видите только вы "
             "и ваши сотрудники, клиент — только свой счёт."),
            ("Что если потеряю или сменю телефон?",
             "Ничего не пропадёт. Войдите в Telegram на новом телефоне и откройте бота — всё на месте."),
            ("Можно добавить сотрудника?",
             "Да. Отправьте сотруднику ссылку-приглашение. Он может записывать продажи и оплаты, а удаление "
             "записей и настройки доступны только руководителю."),
            ("А если я продаю в долларах?",
             "Каждый товар можно записать в сумах или долларах. Долг считается отдельно по каждой валюте."),
            ("Что будет после пробного периода?",
             "Оплачиваете месяц — продолжаете работать. Без оплаты данные не удаляются и вернутся после оплаты."),
        ],
        'final_title': "Закройте тетрадь сегодня",
        'final_text': "Откройте магазин за минуту — {trial} дней бесплатно.",
        'footer_contact': "Связаться",
        'footer_privacy': "Политика конфиденциальности",
        'footer_rights': "Все права защищены.",
        'screens_alt': "Экран приложения QarzDaptar",
        'privacy_title': "Политика конфиденциальности",
        'privacy_back': "На главную",
        'privacy': [
            ("Какие данные хранятся",
             "Название и тип магазина, Telegram ID и имя владельца и сотрудников, имя, телефон и Telegram ID "
             "клиентов, записи о долгах и оплатах."),
            ("Для чего используются",
             "Только для работы сервиса: учёт долгов и оплат, отправка клиенту запроса на подтверждение и "
             "напоминаний, подготовка отчётов."),
            ("Кто видит данные",
             "Данные магазина видят только владелец и добавленные им сотрудники. Клиент видит только свой счёт. "
             "Данные не продаются и не передаются третьим лицам."),
            ("Хранение и безопасность",
             "Данные хранятся на сервере, резервная копия делается ежедневно. Вход — только через подпись Telegram."),
            ("Удаление",
             "Чтобы удалить данные магазина или клиента, свяжитесь с нами в Telegram."),
        ],
    },
}


def get_lang(request):
    lang = request.GET.get('lang')
    if lang in LANGS:
        return lang
    lang = request.COOKIES.get(LANG_COOKIE)
    return lang if lang in LANGS else 'uz'


def _fill(value, **kw):
    """Matnlardagi {trial}, {bot} kabi o'rinlarni to'ldirish (ichma-ich ro'yxatlarda ham)."""
    if isinstance(value, str):
        return value.format(**kw)
    if isinstance(value, (list, tuple)):
        return type(value)(_fill(v, **kw) for v in value)
    return value


def page_context(request):
    lang = get_lang(request)
    t = {k: _fill(v, trial=TRIAL_DAYS, bot=settings.BOT_USERNAME) for k, v in TEXT[lang].items()}
    t['features'] = [{'icon': ICONS[i], 'title': a, 'text': b} for i, a, b in t['features']]
    t['problems'] = [{'icon': ICONS[i], 'problem': a, 'solution': b} for i, a, b in t['problems']]
    names = CATEGORY_RU if lang == 'ru' else dict(Shop.CATEGORY_CHOICES)
    return {
        'lang': lang,
        't': t,
        'icons': ICONS,
        'shop_types': [f"{CATEGORY_EMOJI[code]} {names[code]}" for code, _ in Shop.CATEGORY_CHOICES
                       if code != 'other'],
        'price': f"{settings.SUBSCRIPTION_PRICE:,}".replace(',', ' '),
        'signup_url': f"https://t.me/{settings.BOT_USERNAME}?start=signup",
        'site_url': f"https://{settings.SITE_DOMAIN}",
    }


def _render(request, template):
    response = render(request, template, page_context(request))
    if request.GET.get('lang') in LANGS:
        response.set_cookie(LANG_COOKIE, request.GET['lang'], max_age=365 * 24 * 3600, samesite='Lax')
    return response


def landing(request):
    return _render(request, 'landing.html')


def privacy_view(request):
    return _render(request, 'privacy.html')
