import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import click, payme


@method_decorator(csrf_exempt, name="dispatch")
class PaymeView(View):
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": payme.PaymeError(payme.ERR_PARSE, "Parse error").as_dict(), "id": None})
        rpc_id = body.get("id")
        if not payme.check_auth(request.headers.get("Authorization", "")):
            return JsonResponse({"error": payme.PaymeError(payme.ERR_AUTH, "Недостаточно привилегий").as_dict(), "id": rpc_id})
        try:
            result = payme.dispatch(body.get("method", ""), body.get("params") or {})
        except payme.PaymeError as e:
            return JsonResponse({"error": e.as_dict(), "id": rpc_id})
        return JsonResponse({"result": result, "id": rpc_id})


@method_decorator(csrf_exempt, name="dispatch")
class ClickPrepareView(View):
    def post(self, request):
        return JsonResponse(click.prepare(request.POST.dict()))


@method_decorator(csrf_exempt, name="dispatch")
class ClickCompleteView(View):
    def post(self, request):
        return JsonResponse(click.complete(request.POST.dict()))
