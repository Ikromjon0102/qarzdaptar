import html

from . import telegram


def send_confirmation_request(telegram_id,  debt_obj, domain):
    """
    Mijozga 'Tasdiqlash' tugmasi bilan xabar yuboradi.
    Tugma bosilganda Telegram Mini App ochiladi.
    """
    web_app_url = f"https://{domain}/debt/{debt_obj.uuid}/"
    
    # --- Multicurrency Logic ---
    sum_parts = []
    
    # Agar so'm qismi bo'lsa (0 dan katta bo'lsa)
    if debt_obj.amount_uzs and debt_obj.amount_uzs > 0:
        # 1,000,000 ko'rinishida formatlaymiz va vergulni probelga almashtiramiz
        uzs_fmt = f"{debt_obj.amount_uzs:,.0f}".replace(",", " ")
        sum_parts.append(f"{uzs_fmt} so'm")
        
    # Agar dollar qismi bo'lsa
    if debt_obj.amount_usd and debt_obj.amount_usd > 0:
        # $100.50 ko'rinishida
        usd_fmt = f"${debt_obj.amount_usd:,.2f}"
        sum_parts.append(usd_fmt)
        
    # Ikkalasini birlashtiramiz (Masalan: "500 000 so'm + $50")
    total_str = " + ".join(sum_parts) if sum_parts else "0 so'm"
    # ---------------------------

    title = "🔁 <b>Nasiya qayta yuborildi</b>" if debt_obj.reject_reason else "🆕 <b>Yangi xarid!</b>"
    note = f"💬 <b>Do'kon izohi:</b> {html.escape(debt_obj.shop_note)}\n\n" if debt_obj.shop_note else ""
    text = (
        f"{title}\n\n"
        f"🛒 <b>Tovarlar:</b>\n{debt_obj.items}\n\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"💰 <b>Jami:</b> {total_str}\n\n"
        f"{note}"
        f"Iltimos, pastdagi tugmani bosib tasdiqlang yoki rad eting."
    )
    reply_markup = {"inline_keyboard": [[{"text": "📝 Ko'rish va Tasdiqlash", "web_app": {"url": web_app_url}}]]}
    telegram.send_message(telegram_id, text, reply_markup=reply_markup)
