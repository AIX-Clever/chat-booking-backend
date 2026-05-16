#!/usr/bin/env python3
"""
Valida compatibilidad retroactiva del schema GraphQL usando graphql-core.

Política:
  - Falla en cualquier breaking change detectado por graphql-core.
  - EXCEPCIÓN: FIELD_CHANGED_KIND donde el único cambio es quitar el `!`
    (T! -> T), porque los clientes que usan try/catch lo manejan correctamente
    y es necesario para propagar errores de AppSync Direct Lambda.

Uso: python3 validate_schema_diff.py OLD_SCHEMA.graphql NEW_SCHEMA.graphql
"""

import re
import sys

try:
    from graphql import build_schema, find_breaking_changes
    from graphql.utilities.find_breaking_changes import BreakingChangeType
except ImportError:
    print("Error: instala graphql-core: pip install graphql-core")
    sys.exit(1)

APPSYNC_DIRECTIVES = [
    "@aws_api_key", "@aws_cognito_user_pools", "@aws_lambda",
    "@aws_iam", "@aws_oidc", "@aws_auth", "@aws_publish", "@aws_subscribe",
]


def strip_directives(content: str) -> str:
    for d in APPSYNC_DIRECTIVES:
        content = re.sub(rf'{re.escape(d)}(\([^)]*\))?', '', content)
    return content


def is_nullability_relaxation(description: str) -> bool:
    """
    Devuelve True si la descripción del FIELD_CHANGED_KIND corresponde a
    quitar un ! (ej. 'X changed type from Foo! to Foo.').
    """
    import re
    m = re.search(r"changed type from (\S+)! to (\S+)\.", description)
    if not m:
        return False
    return m.group(1) == m.group(2)


def main():
    if len(sys.argv) != 3:
        print("Uso: validate_schema_diff.py OLD_SCHEMA.graphql NEW_SCHEMA.graphql")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        old_raw = f.read()
    with open(sys.argv[2]) as f:
        new_raw = f.read()

    old_schema = build_schema(strip_directives(old_raw))
    new_schema = build_schema(strip_directives(new_raw))

    all_breaking = find_breaking_changes(old_schema, new_schema)

    allowed = []
    unexpected = []

    for change in all_breaking:
        if (change.type == BreakingChangeType.FIELD_CHANGED_KIND
                and is_nullability_relaxation(change.description)):
            allowed.append(change)
        else:
            unexpected.append(change)

    if allowed:
        print("Cambios permitidos (relajación de nullability T! -> T):")
        for c in allowed:
            print(f"  ⚠ {c.description}")

    if unexpected:
        print("\nBREAKING CHANGES no permitidos:")
        for c in unexpected:
            print(f"  ✖ [{c.type.name}] {c.description}")
        sys.exit(1)

    print("\nSchema retrocompatible ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
