import hashlib
import os
import sys

def calculate_shared_hash(shared_dir):
    if not os.path.exists(shared_dir):
        return "no-shared-folder"
    
    hash_md5 = hashlib.md5()
    files = []
    for root, dirs, filenames in os.walk(shared_dir):
        # Exclude __pycache__ and other hidden dirs
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
        
        for filename in filenames:
            if not filename.endswith('.pyc') and not filename.endswith('.pyo') and filename != '.DS_Store':
                files.append(os.path.join(root, filename))
    
    # Sort for determinism
    files.sort()
    
    for filepath in files:
        # Include relative path in hash to detect moves
        rel_path = os.path.relpath(filepath, shared_dir)
        # Use consistent path separators (forward slashes) for hashing
        normalized_path = rel_path.replace(os.sep, '/')
        
        hash_md5.update(normalized_path.encode())
        
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
                
    return hash_md5.hexdigest()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_shared.py <shared_dir>")
        sys.exit(1)
    
    print(calculate_shared_hash(sys.argv[1]))
