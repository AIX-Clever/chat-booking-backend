"""
Migración: crear key "Widget Embed" para tenants que no tienen una.

Contexto: antes del 2026-05-06 el onboarding solo creaba un key "Sitio Web".
Este script recorre todos los tenants y crea el key "Widget Embed" faltante.
El key "Sitio Web" existente no se modifica.

Uso:
    python scripts/backfill_widget_embed_keys.py [--dry-run]

    --dry-run  Simula el proceso sin escribir en DynamoDB.
"""
import sys
import os
import secrets
import argparse
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# Añadir el raíz del backend al path para importar shared
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.utils import generate_api_key

REGION = os.environ.get('AWS_REGION', 'us-east-2')
TENANTS_TABLE = os.environ.get('TENANTS_TABLE', 'ChatBooking-Tenants')
API_KEYS_TABLE = os.environ.get('API_KEYS_TABLE', 'ChatBooking-ApiKeys')

WIDGET_EMBED_NAME = "Widget Embed"


def scan_all_tenants(table):
    items = []
    response = table.scan(ProjectionExpression="tenantId, #n", ExpressionAttributeNames={"#n": "name"})
    items.extend(response.get('Items', []))
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            ProjectionExpression="tenantId, #n",
            ExpressionAttributeNames={"#n": "name"},
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))
    return items


def get_keys_for_tenant(api_keys_table, tenant_id):
    items = []
    response = api_keys_table.query(
        KeyConditionExpression=Key('tenantId').eq(tenant_id)
    )
    items.extend(response.get('Items', []))
    while 'LastEvaluatedKey' in response:
        response = api_keys_table.query(
            KeyConditionExpression=Key('tenantId').eq(tenant_id),
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))
    return items


def has_widget_embed_key(keys):
    return any(k.get('name') == WIDGET_EMBED_NAME for k in keys)


def create_widget_embed_key(api_keys_table, tenant_id, dry_run):
    public_key, hashed_key = generate_api_key()
    api_key_id = f"key_{secrets.token_hex(4)}"
    key_preview = f"{public_key[:8]}...{public_key[-4:]}"
    now = datetime.now(timezone.utc).isoformat()

    item = {
        'tenantId': tenant_id,
        'apiKeyId': api_key_id,
        'apiKeyHash': hashed_key,
        'status': 'ACTIVE',
        'name': WIDGET_EMBED_NAME,
        'keyPreview': key_preview,
        'allowedOrigins': ['*'],
        'rateLimit': 1000,
        'createdAt': now,
    }

    if not dry_run:
        api_keys_table.put_item(Item=item)

    return api_key_id, key_preview


def main():
    parser = argparse.ArgumentParser(description="Backfill Widget Embed API keys")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin escribir en DynamoDB")
    args = parser.parse_args()

    dry_run = args.dry_run
    label = "[DRY-RUN] " if dry_run else ""

    print(f"{label}Iniciando backfill de keys 'Widget Embed'")
    print(f"Región:          {REGION}")
    print(f"Tenants table:   {TENANTS_TABLE}")
    print(f"API Keys table:  {API_KEYS_TABLE}")
    print()

    session = boto3.Session(region_name=REGION)
    dynamodb = session.resource('dynamodb')
    tenants_table = dynamodb.Table(TENANTS_TABLE)
    api_keys_table = dynamodb.Table(API_KEYS_TABLE)

    tenants = scan_all_tenants(tenants_table)
    total = len(tenants)
    print(f"Tenants encontrados: {total}\n")

    stats = {'scanned': 0, 'skipped': 0, 'created': 0, 'errors': 0}

    for tenant in tenants:
        tenant_id = tenant.get('tenantId')
        tenant_name = tenant.get('name', '(sin nombre)')
        stats['scanned'] += 1
        prefix = f"[{stats['scanned']}/{total}] {tenant_name} ({tenant_id})"

        try:
            keys = get_keys_for_tenant(api_keys_table, tenant_id)
            existing_names = [k.get('name', '(sin nombre)') for k in keys]

            if has_widget_embed_key(keys):
                print(f"{prefix} — ya tiene 'Widget Embed'. Omitido.")
                stats['skipped'] += 1
            else:
                api_key_id, key_preview = create_widget_embed_key(api_keys_table, tenant_id, dry_run)
                action = "Simulado" if dry_run else "Creado"
                print(f"{prefix} — {action} key '{WIDGET_EMBED_NAME}' (id={api_key_id}, preview={key_preview}). Keys previas: {existing_names}")
                stats['created'] += 1

        except Exception as e:
            print(f"{prefix} — ERROR: {e}")
            stats['errors'] += 1

    print(f"\n--- {label}Backfill completado ---")
    print(f"Total escaneados:  {stats['scanned']}")
    print(f"Omitidos (OK):     {stats['skipped']}")
    print(f"{'Simulados' if dry_run else 'Creados'}:         {stats['created']}")
    print(f"Errores:           {stats['errors']}")

    if stats['errors'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
