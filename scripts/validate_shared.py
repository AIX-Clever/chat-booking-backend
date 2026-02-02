import hashlib
import os
import sys

def calculate_shared_hash(shared_dir):
    if not os.path.exists(shared_dir):
        return "no-shared-folder"
    
    hash_md5 = hashlib.md5()
    files = []
    for root, _, filenames in os.walk(shared_dir):
        for filename in filenames:
            if not filename.endswith('.pyc') and '__pycache__' not in root:
                files.append(os.path.join(root, filename))
    
    # Sort for determinism
    files.sort()
    
    for filepath in files:
        # Include relative path in hash to detect moves
        rel_path = os.path.relpath(filepath, shared_dir)
        hash_md5.update(rel_path.encode())
        
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
                
    return hash_md5.hexdigest()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_shared.py <shared_dir>")
        sys.exit(1)
    
    print(calculate_shared_hash(sys.argv[1]))
