import json
import boto3
import os
from typing import List, Dict, Any

class VectorRepository:
    def __init__(self, db_cluster_arn: str, db_secret_arn: str):
        self.rds_client = boto3.client('rds-data')
        self.db_cluster_arn = db_cluster_arn
        self.db_secret_arn = db_secret_arn
        self.database_name = 'chatbookingvec'

    def _execute(self, sql: str, parameters: List[Dict[str, Any]] = None):
        """Helper to execute SQL via Data API"""
        if parameters is None:
            parameters = []
            
        return self.rds_client.execute_statement(
            resourceArn=self.db_cluster_arn,
            secretArn=self.db_secret_arn,
            database=self.database_name,
            sql=sql,
            parameters=parameters,
            includeResultMetadata=True
        )

    def search(self, tenant_id: str, embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search for most similar text chunks using pgvector cosine similarity.
        STRICTLY SCOPED TO TENANT_ID.
        """
        # Convert embedding list to string representation for SQL '[...]'
        embedding_str = json.dumps(embedding)
        
        sql = """
            SELECT content, 1 - (embedding <=> :embedding::vector) as similarity
            FROM embeddings
            WHERE tenant_id = :tenant_id
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """
        
        params = [
            {'name': 'tenant_id', 'value': {'stringValue': tenant_id}},
            {'name': 'embedding', 'value': {'stringValue': embedding_str}},
            {'name': 'limit', 'value': {'longValue': limit}}
        ]
        
        response = self._execute(sql, params)
        
        # Parse Data API structure (list of lists of fields)
        results = []
        if 'records' in response:
            for record in response['records']:
                # safely extract fields assuming order: content, similarity
                content = record[0].get('stringValue', '')
                similarity = record[1].get('doubleValue', 0.0)
                results.append({'content': content, 'similarity': similarity})
                
        return results

    def insert(self, tenant_id: str, content: str, embedding: List[float]) -> None:
        """
        Insert a new embedding record.
        """
        embedding_str = json.dumps(embedding)
        
        sql = """
            INSERT INTO embeddings (id, tenant_id, content, embedding, created_at)
            VALUES (gen_random_uuid(), :tenant_id, :content, :embedding::vector, NOW())
        """
        
        params = [
            {'name': 'tenant_id', 'value': {'stringValue': tenant_id}},
            {'name': 'content', 'value': {'stringValue': content}},
            {'name': 'embedding', 'value': {'stringValue': embedding_str}}
        ]
        
        self._execute(sql, params)

    def __repr__(self):
        return f"<VectorRepository arn={self.db_cluster_arn}>"
