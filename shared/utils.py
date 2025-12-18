import uuid
from datetime import datetime, timezone

def generate_id(prefix: str = 'id') -> str:
    """Generate a unique ID with prefix"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"
