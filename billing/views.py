import json
import logging

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import plans
from core.permissions import shop_admin_required
from . import click, payme
from .models import SubscriptionPayment

logger = logging.getLogger(__name__)

def providers_enabled():
    return {
        'payme': bool(settings.PAYME_MERCHANT_ID and settings.PAYME_KEY),
        'click': bool(settings.CLICK_SERVICE_ID and settings.CLICK_MERCHANT_ID and settings.CLICK_SECRET_KEY),
    }


@shop_admin_required
@require_POST
def start_payment(request):
    """Tanlangan tarif va davr (oy/yil) uchun to'lov yaratib, Payme/Click sahifasiga yuboradi."""
    from core.views import get_current_shop

    shop = get_current_shop(request)
    provider = request.POST.get('provider')
    plan = request.POST.get('plan')
    period = request.POST.get('period')
    if plan not in plans.PAID or period not in plans.PERIODS or not providers_enabled().get(provider) or not shop:
        messages.error(request, "Bu to'lov usuli hozircha mavjud emas.")
        return redirect('pricing_page')

    payment = SubscriptionPayment.objects.create(shop=shop, provider=provider, plan=plan,
                                                 months=plans.PERIODS[period],
                                                 amount=plans.period_price(plan, period, shop))
    return_url = f"https://{settings.SITE_DOMAIN}{reverse('pricing_page')}?payment={payment.id}"
    url = payme.checkout_url(payment, return_url) if provider == 'payme' else click.pay_url(payment, return_url)
    return redirect(url)


@csrf_exempt
@require_POST
def payme_endpoint(request):
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse(payme.error_response(None, payme.PARSE_ERROR))
    response = payme.handle(body, request.headers.get('Authorization', ''))
    if 'error' in response:
        logger.info("Payme %s -> %s", body.get('method') if isinstance(body, dict) else '?', response['error']['code'])
    return JsonResponse(response)


@csrf_exempt
@require_POST
def click_endpoint(request):
    response = click.handle(request.POST.dict())
    if response['error'] != click.SUCCESS:
        logger.info("Click action=%s -> %s", request.POST.get('action'), response['error'])
    return JsonResponse(response)
