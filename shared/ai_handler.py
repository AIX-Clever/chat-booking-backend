import json
import boto3
import logging
from typing import List, Dict, Any
from shared.infrastructure.vector_repository import VectorRepository

logger = logging.getLogger()

class AIHandler:
import os

    def __init__(self, vector_repo: VectorRepository):
        self.bedrock_runtime = boto3.client('bedrock-runtime')
        self.vector_repo = vector_repo
        # Models
        self.embedding_model_id = os.environ.get('EMBEDDING_MODEL_ID', 'amazon.titan-embed-text-v2:0')
        self.llm_model_id = os.environ.get('LLM_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0') 

    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding using Titan v2"""
        try:
            response = self.bedrock_runtime.invoke_model(
                modelId=self.embedding_model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": text,
                    "dimensions": 1024,
                    "normalize": True
                })
            )
            response_body = json.loads(response['body'].read())
            return response_body['embedding']
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}")
            raise e

    def generate_response(self, tenant_id: str, history: List[Dict], user_message: str) -> str:
        """
        Main RAG Flow:
        1. Embed user query.
        2. Retrieve relevant context from Aurora (Vector Search).
        3. Construct Prompt with Context + History.
        4. Invoke Claude for answer.
        """
        
        # 1. Embed
        query_embedding = self.get_embedding(user_message)
        
        # 2. Retrieve Context
        relevant_chunks = self.vector_repo.search(tenant_id, query_embedding, limit=3)
        context_str = "\n\n".join([c['content'] for c in relevant_chunks])
        
        # 3. Construct Prompt
        system_prompt = f"""You are a helpful AI assistant for a business.
        Use the following retrieved context to answer the user's question. 
        If the answer is not in the context, say you don't know, or try to be helpful based on general knowledge if appropriate but prioritize the context.
        
        Context:
        {context_str}
        """

        # Format messages for Claude 3 (Messages API)
        # Convert history format if needed. Assuming history is list of {role, content}
        messages = []
        for msg in history[-5:]: # Keep last 5 turns
            role = 'user' if msg.get('role') == 'user' else 'assistant'
            messages.append({"role": role, "content": msg.get('content')})
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

        # 4. Invoke LLM
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": messages,
            "temperature": 0.7
        })

        try:
            response = self.bedrock_runtime.invoke_model(
                modelId=self.llm_model_id,
                body=body
            )
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
        except Exception as e:
            logger.error(f"Error generating response from Bedrock (Model: {self.llm_model_id}): {str(e)}", exc_info=True)
            return "I apologize, but I'm having trouble connecting to my brain right now."
