import os
import httpx
from google import genai
from google.genai import types
import urllib.parse
import uuid

API_KEY = os.environ.get("GEMINI_API_KEY", "")
DREAM_MODEL = os.environ.get("GEMINI_DREAM_MODEL", "gemini-2.5-pro")
SEARCH_MODEL = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

client = None
if API_KEY:
    client = genai.Client(api_key=API_KEY)

async def create_corpus(display_name: str) -> str:
    if not API_KEY: return f"corpora/{uuid.uuid4().hex}"
    url = f"{BASE_URL}/corpora?key={API_KEY}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json={"displayName": display_name})
        if resp.status_code == 429: 
             print("Corpus limit reached. Using mock corpus id.")
             return f"corpora/{uuid.uuid4().hex}"
        if resp.status_code != 200:
            print("create_corpus error:", resp.text)
        resp.raise_for_status()
        return resp.json()["name"]

async def list_documents(corpus_name: str) -> list[dict]:
    if not API_KEY or "corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name: 
        return []
    url = f"{BASE_URL}/{corpus_name}/documents?key={API_KEY}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(url)
        if resp.status_code in [404, 403, 400]: return []
        if resp.status_code == 501: return [] # Method not found
        resp.raise_for_status()
        return resp.json().get("documents", [])

async def create_document(corpus_name: str, display_name: str) -> str:
    if not API_KEY or "corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name: 
        return f"{corpus_name}/documents/{uuid.uuid4().hex}"
    url = f"{BASE_URL}/{corpus_name}/documents?key={API_KEY}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json={"displayName": display_name})
        if resp.status_code in [404, 403, 400]: return f"{corpus_name}/documents/{uuid.uuid4().hex}"
        if resp.status_code == 501: return f"{corpus_name}/documents/{uuid.uuid4().hex}" # fallback
        resp.raise_for_status()
        return resp.json()["name"]

async def get_or_create_document(corpus_name: str, doc_display_name: str) -> str:
    docs = await list_documents(corpus_name)
    for doc in docs:
        if doc.get("displayName") == doc_display_name:
            return doc["name"]
    return await create_document(corpus_name, doc_display_name)

async def delete_document(doc_name: str):
    if not API_KEY: return
    url = f"{BASE_URL}/{doc_name}?key={API_KEY}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.delete(url)
        if resp.status_code not in [200, 404, 403, 400, 501]:
            resp.raise_for_status()

async def list_chunks(doc_name: str) -> list[dict]:
    if not API_KEY: return []
    url = f"{BASE_URL}/{doc_name}/chunks?key={API_KEY}"
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(url)
        if resp.status_code in [404, 403, 400, 501]: return []
        resp.raise_for_status()
        return resp.json().get("chunks", [])

async def create_chunk(doc_name: str, content: str, memory_id: str) -> str:
    if not API_KEY or "corpora/" in doc_name and len(doc_name) > 30 and "-" not in doc_name:
         return f"{doc_name}/chunks/{memory_id}"
    url = f"{BASE_URL}/{doc_name}/chunks?key={API_KEY}"
    payload = {
        "data": {"stringValue": content},
        "customMetadata": [{"key": "memory_id", "stringValue": memory_id}]
    }
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(url, json=payload)
        if resp.status_code in [404, 403, 400, 501]: return f"{doc_name}/chunks/{memory_id}"
        resp.raise_for_status()
        return resp.json()["name"]

async def find_chunk_by_memory_id(doc_name: str, memory_id: str) -> str | None:
    chunks = await list_chunks(doc_name)
    for chunk in chunks:
        if chunk.get("customMetadata"):
            for meta in chunk["customMetadata"]:
                if meta.get("key") == "memory_id" and meta.get("stringValue") == memory_id:
                    return chunk["name"]
    return None

async def update_chunk(corpus_name: str, doc_display_name: str, memory_id: str, content: str):
    doc_name = await get_or_create_document(corpus_name, doc_display_name)
    chunk_name = await find_chunk_by_memory_id(doc_name, memory_id)
    if chunk_name and API_KEY and ("corpora/" not in chunk_name or len(corpus_name) <= 15 or "-" in corpus_name):
        url = f"{BASE_URL}/{chunk_name}?key={API_KEY}"
        payload = {
            "data": {"stringValue": content},
            "customMetadata": [{"key": "memory_id", "stringValue": memory_id}]
        }
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.patch(url, json=payload)
            if resp.status_code not in [404, 403, 400, 501]:
                resp.raise_for_status()
    else:
        await create_chunk(doc_name, content, memory_id)

async def delete_chunk(corpus_name: str, doc_display_name: str, memory_id: str):
    doc_name = await get_or_create_document(corpus_name, doc_display_name)
    chunk_name = await find_chunk_by_memory_id(doc_name, memory_id)
    if chunk_name and API_KEY:
        url = f"{BASE_URL}/{chunk_name}?key={API_KEY}"
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.delete(url)
            if resp.status_code not in [200, 404, 403, 400, 501]:
                resp.raise_for_status()

async def search_corpus(corpus_name: str, query: str) -> list[dict]:
    if not API_KEY or ("corpora/" in corpus_name and len(corpus_name) > 15 and "-" not in corpus_name): 
        return ["mock chunk content"]
    url = f"{BASE_URL}/{corpus_name}:query?key={API_KEY}"
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

async def generate_dream(prompt: str, input_text: str) -> str:
    if not client:
        return f"## [Consolidated] Mock Topic\n{input_text}"
        
    response = client.models.generate_content(
        model=DREAM_MODEL,
        contents=[
            types.Content(role="user", parts=[
                types.Part.from_text(text=f"{prompt}\n\n{input_text}")
            ])
        ]
    )
    return response.text
