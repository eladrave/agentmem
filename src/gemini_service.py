import os
import asyncio
from google import genai
from google.genai import types
from google.genai.errors import ClientError

SERVER_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DREAM_MODEL = os.environ.get("GEMINI_DREAM_MODEL", "gemini-2.5-pro")
SEARCH_MODEL = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")

def get_client(api_key: str = None) -> genai.Client | None:
    key = api_key if api_key and api_key.strip() else SERVER_API_KEY
    if not key or not key.strip(): 
        print("CRITICAL: No API Key found in either explicit argument or SERVER_API_KEY")
        return None
    return genai.Client(api_key=key.strip())

async def create_file_search_store(display_name: str, api_key: str = None) -> str:
    # Instead of creating a buggy fileSearchStore, we will just use a generic user prefix for files
    # This prevents the 10-Corpus limit naturally because Files don't have limits.
    # The 'store_id' will simply act as a custom UUID tag we apply to files.
    import uuid
    return f"store_{uuid.uuid4().hex}"

async def upload_and_attach_file(file_path: str, display_name: str, store_name: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client: return "mock-file-name"
    
    def _process():
        try:
            # We natively upload the file without a fileSearchStore.
            # We use the store_name as a tag in the display_name so we can group them later.
            f = client.files.upload(
                file=file_path,
                config={
                    "display_name": f"{store_name}_{display_name}",
                    "mime_type": "text/plain" # Explicitly use text/plain so Gemini reads it perfectly
                }
            )
            return f.name
        except Exception as e:
            print(f"Error uploading file {display_name}: {e}")
            return "mock-file-name"

    return await asyncio.to_thread(_process)

async def list_files_in_store(store_name: str, api_key: str = None) -> list[dict]:
    client = get_client(api_key)
    if not client: return []
    
    def _list():
        try:
            docs = []
            for f in client.files.list():
                if getattr(f, 'display_name', '').startswith(f"{store_name}_"):
                    docs.append(f)
            return docs
        except Exception as e:
            print(f"List files error: {e}")
            return []
            
    return await asyncio.to_thread(_list)

async def delete_file_from_store(doc_name: str, api_key: str = None):
    # doc_name here is the actual File name (e.g. files/XYZ)
    client = get_client(api_key)
    if not client or "mock-" in doc_name: return
    
    def _delete():
        try:
            client.files.delete(name=doc_name)
        except Exception as e:
            pass # Ignore deletion errors for files that might already be gone
            
    await asyncio.to_thread(_delete)

async def delete_store(store_name: str, api_key: str = None):
    client = get_client(api_key)
    if not client: return
    def _delete():
        try:
            for f in client.files.list():
                if getattr(f, 'display_name', '').startswith(f"{store_name}_"):
                    client.files.delete(name=f.name)
        except Exception as e:
            pass
    await asyncio.to_thread(_delete)

async def search_memory_files(query: str, store_name: str, active_context: str, api_key: str = None) -> str:
    client = get_client(api_key)
    if not client:
        return f"[Fallback Local Search]\n\n{active_context}\n\n(Note: Remote Gemini API is unavailable)."
        
    def _search():
        prompt = f"Search the provided memory files for information regarding: '{query}'.\n\nReturn the exact relevant facts or memory snippets found."
        if active_context:
            prompt += f"\n\nHere are the most recent ACTIVE memories that have not yet been ingested into the file store. Prioritize these if relevant:\n{active_context}"
            
        try:
            # Gather all files belonging to this store
            files = []
            for f in client.files.list():
                if getattr(f, 'display_name', '').startswith(f"{store_name}_"):
                    files.append(f)
                    
            if not files and not active_context:
                return f"I could not find any information regarding '{query}' in your memories."
                
            # Feed the files and prompt directly to the context window (RAG)
            contents = files + [prompt]
            res = client.models.generate_content(
                model=SEARCH_MODEL,
                contents=contents
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
