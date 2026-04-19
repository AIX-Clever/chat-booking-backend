import os
import re

def process_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    original = content
    
    # Replace client_name=...
    def repl_client(match):
        val = match.group(1)
        name = val.strip('\'"')
        parts = name.split(' ', 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ''
        return f'client_first_name="{first}", client_last_name="{last}"'
    
    content = re.sub(r'client_name=([\'"][^\'"]+[\'"])', repl_client, content)

    # Replace CustomerInfo(..., name=...)
    def repl_cust(match):
        inner = match.group(1)
        def repl_n(m):
            val = m.group(1)
            name = val.strip('\'"')
            parts = name.split(' ', 1)
            first = parts[0]
            last = parts[1] if len(parts) > 1 else ''
            return f'given_name="{first}", family_name="{last}"'
        inner = re.sub(r'\bname=([\'"][^\'"]+[\'"])', repl_n, inner)
        return f"CustomerInfo({inner})"

    content = re.sub(r'CustomerInfo\((.*?)\)', repl_cust, content, flags=re.DOTALL)
    
    if content != original:
        with open(file_path, 'w') as f:
            f.write(content)

for root, _, files in os.walk('/Users/marioalvarez/repos/conversacion/chat-booking-backend/tests'):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
