import hashlib
import os
import sys

def calculate_file_md5(filepath):
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def list_shared_md5s(shared_dir):
    if not os.path.exists(shared_dir):
        print(f"Error: {shared_dir} does not exist")
        return
    
    files = []
    for root, dirs, filenames in os.walk(shared_dir):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
        for filename in filenames:
            if not filename.endswith('.pyc') and not filename.endswith('.pyo') and filename != '.DS_Store':
                files.append(os.path.join(root, filename))
    
    files.sort()
    
    for filepath in files:
        rel_path = os.path.relpath(filepath, shared_dir)
        normalized_path = rel_path.replace(os.sep, '/')
        md5 = calculate_file_md5(filepath)
        print(f"{md5}  {normalized_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python list_md5s.py <shared_dir>")
        sys.exit(1)
    list_shared_md5s(sys.argv[1])
