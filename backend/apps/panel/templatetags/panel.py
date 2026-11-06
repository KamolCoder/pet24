from datetime import timedelta
from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def money(v):
    """1234567.5 -> '1 234 568'"""
    if v is None or v == "":
        return "—"
    return f"{Decimal(v):,.0f}".replace(",", " ")


@register.filter
def num(v):
    if v is None:
        return "—"
    d = Decimal(v)
    s = f"{d:,.3f}".rstrip("0").rstrip(".") if d != d.to_integral() else f"{d:,.0f}"
    return s.replace(",", " ")


@register.filter
def pct(v, digits=1):
    if v is None:
        return "—"
    return f"{Decimal(v) * 100:.{int(digits)}f}%"


@register.filter
def signed_pct(v):
    if v is None:
        return ""
    v = Decimal(v) * 100
    return f"{'+' if v > 0 else ''}{v:.1f}%"


@register.filter
def dur(td):
    if td is None:
        return "—"
    if not isinstance(td, timedelta):
        return td
    if td.total_seconds() < 60:
        return f"{int(td.total_seconds())} с"
    minutes = int(td.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} мин"
    h, m = divmod(minutes, 60)
    if h < 48:
        return f"{h} ч {m} мин"
    return f"{h // 24} дн {h % 24} ч"


@register.filter
def ago(dt):
    if not dt:
        return "никогда"
    if timezone.now() - dt < timedelta(minutes=1):
        return "только что"
    return f"{timesince(dt).split(',')[0]} назад"


@register.filter
def stale(dt, minutes=30):
    return dt is None or timezone.now() - dt > timedelta(minutes=int(minutes))


@register.filter
def status_badge(status):
    return {
        "new": "off", "paid": "warn", "assembling": "warn", "courier_search": "warn",
        "courier_assigned": "info", "delivering": "info", "delivered": "ok", "problem": "bad", "canceled": "off",
        "pending": "off", "refund_required": "bad", "refunded": "off",
        "searching": "warn", "assigned": "info", "picked_up": "info", "failed": "bad", "created": "off",
    }.get(status, "off")


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Current query string with some params replaced: {% qs page=2 %}"""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    return "?" + q.urlencode() if q else "?"
