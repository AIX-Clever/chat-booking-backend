import io
import re
from typing import List

class DocumentProcessor:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def process(self, file_content: bytes, file_type: str) -> List[str]:
        """
        Extract text and split into chunks.
        """
        text = ""
        if file_type.lower() == 'pdf':
            text = self._extract_text_from_pdf(file_content)
        else:
            # Assume text/plain
            text = file_content.decode('utf-8', errors='ignore')
            
        return self._split_text(text)

    def _extract_text_from_pdf(self, file_content: bytes) -> str:
        """
        Extract text from PDF bytes using pypdf.
        """
        try:
            import pypdf
            pdf_file = io.BytesIO(file_content)
            reader = pypdf.PdfReader(pdf_file)
            text = []
            for page in reader.pages:
                text.append(page.extract_text())
            return "\n".join(text)
        except ImportError:
            raise ImportError("pypdf is required for PDF processing")

    def _split_text(self, text: str) -> List[str]:
        """
        Simple overlapping chunk splitter.
        """
        if not text:
            return []
            
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + self.chunk_size
            
            # Use space to break appropriately if possible
            if end < text_len:
                # Find last space within the chunk
                last_space = text.rfind(' ', start, end)
                if last_space != -1 and last_space > start:
                    end = last_space
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            # Move start forward by chunk_size - overlap
            start += self.chunk_size - self.chunk_overlap
            
            # Avoid infinite loop if no progress (shouldn't happen with strict math but good safety)
            if start >= end:
                start = end
                
        return chunks
