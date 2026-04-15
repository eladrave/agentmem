import os
import asyncio
from google import genai
from google.genai import types
from google.genai.errors import ClientError

SERVER_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DREAM_MODEL = os.environ.get("GEMINI_DREAM_MODEL", "gemini-2.5-pro")
SEARCH_MODEL = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")

def get_client(api_key: str = None) -> genai.Client | None:
    key = api_key if api_key else SERVER_API_KEY
    if not key: return None
    return genai.Client(api_key=key)

async def create_file_search_store(display_name: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client: return f"mock-store-id"
    
    def _create():
        try:
            store = client.file_search_stores.create(config={"display_name": display_name})
            return store.name
        except ClientError as e:
            if "RESOURCE_EXHAUSTED" in str(e):
                return "mock-store-id"
            raise e
            
    return await asyncio.to_thread(_create)

async def upload_and_attach_file(file_path: str, display_name: str, store_name: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client or store_name == "mock-store-id": return "mock-file-name"
    
    def _process():
        try:
            op = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name,
                file=file_path,
                config={"display_name": display_name}
            )
            return op.response.document_name
        except Exception as e:
            print(f"Error uploading file {display_name}: {e}")
            return "mock-file-name"

    return await asyncio.to_thread(_process)

async def list_files_in_store(store_name: str, api_key: str = None) -> list[dict]:
    client = get_client(api_key)
    if not client or store_name == "mock-store-id": return []
    
    def _list():
        try:
            docs = []
            for d in client.file_search_stores.documents.list(parent=store_name):
                docs.append(d)
            return docs
        except Exception as e:
            print(f"List files error: {e}")
            return []
            
    return await asyncio.to_thread(_list)

async def delete_file_from_store(doc_name: str, api_key: str = None):
    client = get_client(api_key)
    if not client or "mock-" in doc_name: return
    
    def _delete():
        try:
            client.file_search_stores.documents.delete(
                name=doc_name, 
                config={"force": True}
            )
        except Exception as e:
            print(f"Failed to delete {doc_name}: {e}")
            
    await asyncio.to_thread(_delete)

async def delete_store(store_name: str, api_key: str = None):
    client = get_client(api_key)
    if not client or "mock-" in store_name: return
    def _delete():
        try:
            client.file_search_stores.delete(name=store_name, config={"force": True})
        except Exception as e:
            pass
    await asyncio.to_thread(_delete)

async def search_memory_files(query: str, store_name: str, active_context: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client or store_name == "mock-store-id":
        return f"[Fallback Local Search]\n\n{active_context}\n\n(Note: Remote Gemini File Search Store is unavailable or quota exceeded)."
        
    def _search():
        prompt = f"Search the user's memories for information regarding: '{query}'.\n\nReturn the exact relevant facts or memory snippets found."
        if active_context:
            prompt += f"\n\nHere are the most recent ACTIVE memories that have not yet been ingested into the file store. Prioritize these if relevant:\n{active_context}"
            
        tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[store_name]
            )
        )
        try:
            res = client.models.generate_content(
                model=SEARCH_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[tool]
                )
            )
            return res.text
        except Exception as e:
            return f"Search Error: {str(e)}"
            
    return await asyncio.to_thread(_search)

async def generate_dream(prompt: str, input_text: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client:
        return f"## [Consolidated] Mock Topic\n{input_text}"
        
    def _dream():
        res = client.models.generate_content(
            model=DREAM_MODEL,
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_text(text=f"{prompt}\n\n{input_text}")
                ])
            ]
        )
        return res.text
        
    return await asyncio.to_thread(_dream)
