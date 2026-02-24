import os
import re
import sys
import json
from typing import List, Dict, Any

try:
    from graphql import build_schema, parse, validate, GraphQLError
except ImportError:
    print("Error: 'graphql-core' library not found.")
    print("Please install it using: pip install graphql-core --break-system-packages")
    sys.exit(1)

# Configuration: Paths to repositories
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SCHEMA_PATH = os.path.join(BASE_DIR, "chat-booking-backend/infra/schema.graphql")

FRONTEND_REPOS = [
    "chat-booking-admin",
    "chat-booking-widget",
    "chat-booking-onboarding",
    "chat-booking-embedded-widget"
]

APPSYNC_DIRECTIVES = [
    "@aws_api_key",
    "@aws_cognito_user_pools",
    "@aws_lambda",
    "@aws_iam",
    "@aws_oidc",
    "@aws_auth",
    "@aws_publish",
    "@aws_subscribe"
]

def strip_directives(content: str) -> str:
    for directive in APPSYNC_DIRECTIVES:
        # Match directive with optional parentheses and content: @directive(...) or @directive
        content = re.sub(rf'{directive}(\([^)]*\))?', '', content)
    return content

def load_schema(path: str):
    if not os.path.exists(path):
        print(f"Error: Schema not found at {path}")
        sys.exit(1)
    with open(path, 'r') as f:
        schema_content = f.read()
    
    # Strip directives from schema too, as graphql-core doesn't know them
    cleaned_schema = strip_directives(schema_content)
    
    try:
        return build_schema(cleaned_schema)
    except Exception as e:
        print(f"Error parsing schema at {path}: {e}")
        # Print a bit of context for the error
        sys.exit(1)

def extract_queries_from_ts(file_path: str) -> List[str]:
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Simple regex to find template literals assigned to export const or similar
    # This works for the common pattern in the repositories: export const NAME = ` query ... `
    query_blocks = re.findall(r'export const \w+ = `([\s\S]+?)`;', content)
    
    results = []
    for query in query_blocks:
        results.append(strip_directives(query.strip()))
    
    return results

def validate_queries(schema, repo_name: str):
    repo_path = os.path.join(BASE_DIR, repo_name)
    queries_file = os.path.join(repo_path, "src/graphql/queries.ts")
    
    if not os.path.exists(queries_file):
        # Fail-safe check: some repos might use src/graphql/index.ts or similar?
        # For now, stick to known locations from search.
        print(f"Skipping {repo_name}: no queries.ts found.")
        return True

    print(f"Validating {repo_name}...")
    queries = extract_queries_from_ts(queries_file)
    
    all_valid = True
    for query_str in queries:
        if not query_str: continue
        try:
            document = parse(query_str)
            errors = validate(schema, document)
            if errors:
                all_valid = False
                print(f"  [X] Error in {repo_name}:")
                # Try to extract operation name for better reporting
                op_match = re.search(r'(query|mutation|subscription)\s+(\w+)', query_str)
                op_name = op_match.group(2) if op_match else "Unknown Operation"
                print(f"      Operation: {op_name}")
                for err in errors:
                    print(f"      - {err.message}")
            # else:
            #    print(f"  [V] Validated operation.")
        except GraphQLError as e:
            all_valid = False
            print(f"  [X] Syntax Error in {repo_name}: {e}")
            # print(f"DEBUG Query:\n{query_str}")
        except Exception as e:
            all_valid = False
            print(f"  [X] Unexpected Error in {repo_name}: {e}")
            
    return all_valid

def main():
    print("--- GraphQL Contract Validator ---")
    schema = load_schema(SCHEMA_PATH)
    
    overall_success = True
    for repo in FRONTEND_REPOS:
        if not validate_queries(schema, repo):
            overall_success = False
            
    print("-" * 34)
    if overall_success:
        print("RESULT: All contracts validated successfully! ✅")
        sys.exit(0)
    else:
        print("RESULT: Contract validation FAILED! ❌")
        sys.exit(1)

if __name__ == "__main__":
    main()
