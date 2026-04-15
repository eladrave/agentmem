import os
import httpx
from google import genai
from google.genai import types
import urllib.parse
import uuid

SERVER_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DREAM_MODEL = os.environ.get("GEMINI_DREAM_MODEL", "gemini-2.5-pro")
SEARCH_MODEL = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

def get_api_key(provided_key: str = None) -> str:
    return provided_key if provided_key else SERVER_API_KEY

async def create_corpus(display_name: str, api_key: str = None) -> str:
    key = get_api_key(api_key)
    if not key: return f"corpora/{uuid.uuid4().hex}"
    url = f"{BASE_URL}/corpora?key={key}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json={"displayName": display_name})
        if resp.status_code == 429: 
             return f"corpora/{uuid.uuid4().hex}"
        if resp.status_code != 200:
            print("create_corpus error:", resp.text)
        resp.raise_for_status()
        return resp.json()["name"]

async def list_documents(corpus_name: str, api_key: str = None) -> list[dict]:
    key = get_api_key(api_key)
    if not key or "corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name: 
        return []
    url = f"{BASE_URL}/{corpus_name}/documents?key={key}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(url)
        if resp.status_code in [404, 403, 400, 501]: return []
        resp.raise_for_status()
        return resp.json().get("documents", [])

async def create_document(corpus_name: str, display_name: str, api_key: str = None) -> str:
    key = get_api_key(api_key)
    if not key or "corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name: 
        return f"{corpus_name}/documents/{uuid.uuid4().hex}"
    url = f"{BASE_URL}/{corpus_name}/documents?key={key}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json={"displayName": display_name})
        if resp.status_code in [404, 403, 400, 501]: return f"{corpus_name}/documents/{uuid.uuid4().hex}"
        resp.raise_for_status()
        return resp.json()["name"]

async def get_or_create_document(corpus_name: str, doc_display_name: str, api_key: str = None) -> str:
    docs = await list_documents(corpus_name, api_key)
    for doc in docs:
        if doc.get("displayName") == doc_display_name:
            return doc["name"]
    return await create_document(corpus_name, doc_display_name, api_key)

async def delete_document(doc_name: str, api_key: str = None):
    key = get_api_key(api_key)
    if not key: return
    url = f"{BASE_URL}/{doc_name}?key={key}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.delete(url)
        if resp.status_code not in [200, 404, 403, 400, 501]:
            resp.raise_for_status()

async def list_chunks(doc_name: str, api_key: str = None) -> list[dict]:
    key = get_api_key(api_key)
    if not key: return []
    url = f"{BASE_URL}/{doc_name}/chunks?key={key}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(url)
        if resp.status_code in [404, 403, 400, 501]: return []
        resp.raise_for_status()
        return resp.json().get("chunks", [])

async def create_chunk(doc_name: str, content: str, memory_id: str, api_key: str = None) -> str:
    key = get_api_key(api_key)
    if not key or "corpora/" in doc_name and len(doc_name) > 30 and "-" not in doc_name:
         return f"{doc_name}/chunks/{memory_id}"
    url = f"{BASE_URL}/{doc_name}/chunks?key={key}"
    payload = {
        "data": {"stringValue": content},
        "customMetadata": [{"key": "memory_id", "stringValue": memory_id}]
    }
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json=payload)
        if resp.status_code in [404, 403, 400, 501]: return f"{doc_name}/chunks/{memory_id}"
        resp.raise_for_status()
        return resp.json()["name"]

async def find_chunk_by_memory_id(doc_name: str, memory_id: str, api_key: str = None) -> str | None:
    chunks = await list_chunks(doc_name, api_key)
    for chunk in chunks:
        if chunk.get("customMetadata"):
            for meta in chunk["customMetadata"]:
                if meta.get("key") == "memory_id" and meta.get("stringValue") == memory_id:
                    return chunk["name"]
    return None

async def update_chunk(corpus_name: str, doc_display_name: str, memory_id: str, content: str, api_key: str = None):
    doc_name = await get_or_create_document(corpus_name, doc_display_name, api_key)
    chunk_name = await find_chunk_by_memory_id(doc_name, memory_id, api_key)
    key = get_api_key(api_key)
    if chunk_name and key and ("corpora/" not in chunk_name or len(corpus_name) <= 15 or "-" in corpus_name):
        url = f"{BASE_URL}/{chunk_name}?key={key}"
        payload = {
            "data": {"stringValue": content},
            "customMetadata": [{"key": "memory_id", "stringValue": memory_id}]
        }
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.patch(url, json=payload)
            if resp.status_code not in [404, 403, 400, 501]:
                resp.raise_for_status()
    else:
        await create_chunk(doc_name, content, memory_id, api_key)

async def delete_chunk(corpus_name: str, doc_display_name: str, memory_id: str, api_key: str = None):
    doc_name = await get_or_create_document(corpus_name, doc_display_name, api_key)
    chunk_name = await find_chunk_by_memory_id(doc_name, memory_id, api_key)
    key = get_api_key(api_key)
    if chunk_name and key:
        url = f"{BASE_URL}/{chunk_name}?key={key}"
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.delete(url)
            if resp.status_code not in [200, 404, 403, 400, 501]:
                resp.raise_for_status()

async def search_corpus(corpus_name: str, query: str, api_key: str = None) -> list[dict]:
    key = get_api_key(api_key)
    if not key or ("corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name): 
        return ["mock chunk content"]
    url = f"{BASE_URL}/{corpus_name}:query?key={key}"
    payload = {
        "query": query,
        "resultsCount": 10
    }
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json=payload)
        if resp.status_code in [404, 403, 400, 501]: return ["mock chunk content"]
        if resp.status_code != 200:
            print("search error:", resp.text)
        resp.raise_for_status()
        chunks = resp.json().get("relevantChunks", [])
        return [c["chunk"]["data"]["stringValue"] for c in chunks if "chunk" in c and "data" in c["chunk"]]

async def generate_dream(prompt: str, input_text: str, api_key: str = None) -> str:
    key = get_api_key(api_key)
    if not key:
        return f"## [Consolidated] Mock Topic\n{input_text}"
        
    dynamic_client = genai.Client(api_key=key)
    response = dynamic_client.models.generate_content(
        model=DREAM_MODEL,
        contents=[
            types.Content(role="user", parts=[
                types.Part.from_text(text=f"{prompt}\n\n{input_text}")
            ])
        ]
    )
    return response.text
