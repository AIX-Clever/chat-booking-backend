import json
import os

from shared.utils import extract_tenant_id
from shared.subscriptions.config import SubscriptionConfig
from shared.subscriptions.mercadopago_client import MercadoPagoClient
from shared.subscriptions.fintoc_client import FintocClient


def lambda_handler(event, _context):
    print(f"[topup] event: {json.dumps(event)}")

    # tenantId always from Cognito identity — never from arguments
    tenant_id = extract_tenant_id(event)
    if not tenant_id:
        raise ValueError("Missing tenantId in request context")

    args = event.get("arguments", {})
    package_id = args.get("packageId", "").lower()
    payment_method = args.get("paymentMethod", "mercadopago").lower()
    back_url = args.get("backUrl") or os.environ.get("DASHBOARD_BASE_URL", "")

    field_name = event.get("info", {}).get("fieldName", "topupWhatsappQuota")
    is_sms = field_name == "topupSmsQuota"
    packages = SubscriptionConfig.SMS_PACKAGES if is_sms else SubscriptionConfig.WHATSAPP_PACKAGES
    channel_label = "SMS" if is_sms else "WhatsApp"
    ref_prefix = "sms-topup" if is_sms else "topup"

    package = packages.get(package_id)
    if not package:
        raise ValueError(f"Invalid packageId: {package_id}. Valid options: {list(packages)}")

    price = package["price"]
    messages = package["messages"]
    title = f"Bolsa {channel_label} {package_id.capitalize()} — {messages} mensajes"
    # external_reference encodes type + tenantId + packageId for webhook routing
    external_reference = f"{ref_prefix}:{tenant_id}:{package_id}"

    print(f"[topup] tenant={tenant_id} package={package_id} price={price} method={payment_method}")

    if payment_method == "fintoc":
        fintoc = FintocClient(environment=os.environ.get("FINTOC_ENV", "live"))
        result = fintoc.create_payment_intent(
            amount=price,
            currency="CLP",
            external_reference=external_reference,
        )
        return {
            "topupId": result["payment_intent_id"],
            "initPoint": result["widget_token"],
            "message": f"Fintoc payment intent created for {title}",
        }

    if payment_method == "mercadopago":
        mp = MercadoPagoClient()
        webhook_url = os.environ.get("WEBHOOK_URL", "")
        result = mp.create_preference(
            title=title,
            amount=float(price),
            external_reference=external_reference,
            back_url=back_url,
            notification_url=webhook_url,
        )
        return {
            "topupId": result.get("id", ""),
            "initPoint": result.get("init_point", ""),
            "message": f"MercadoPago preference created for {title}",
        }

    # manual transfer — no payment gateway, just return package details for the UI
    if payment_method == "transfer":
        return {
            "topupId": f"transfer:{tenant_id}:{package_id}",
            "initPoint": "",
            "message": f"Transferencia bancaria — {title} — ${price:,} CLP",
        }

    raise ValueError(f"Invalid paymentMethod: {payment_method}. Valid: fintoc, mercadopago, transfer")
