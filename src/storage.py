import json
import os
import aiofiles
import asyncio
from datetime import datetime
import uuid
import hashlib
from typing import Dict, Any
import re

DATA_DIR = os.environ.get("DATA_DIR", "/data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DREAM_PROMPT_FILE = os.path.join(DATA_DIR, "dream_prompt.txt")

global_users_lock = asyncio.Lock()
user_locks: Dict[str, asyncio.Lock] = {}

def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

async def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        async with global_users_lock:
            async with aiofiles.open(USERS_FILE, 'w') as f:
                await f.write(json.dumps({"users": {}}))
    
    if not os.path.exists(DREAM_PROMPT_FILE):
        prompt = """You are the cognitive memory consolidation engine for an advanced AI system. Your primary function is to process raw, timestamped short-term memory logs and synthesize them into structured, high-value long-term memories.

You will be provided with memory chunks. 

PROCESS THESE MEMORIES STRICTLY ADHERING TO THE FOLLOWING RULES:
1. Deduplication & Synthesis: Merge redundant or overlapping statements into a single, highly dense narrative. 
2. Chronological Conflict Resolution: If an earlier memory is superseded by a later one, document the final resolved state while briefly noting the evolution.
3. High-Fidelity Extraction: You must absolutely preserve specific entities, metrics, and hard facts. Never generalize technical terminology, code snippets, financial figures, company names, or personal preferences. 
4. Noise Reduction: Discard conversational filler, failed intermediate steps, or meaningless transient states.

OUTPUT FORMAT:
Output strictly in valid Markdown. Do not include introductory or concluding conversational filler.
Group related thoughts together using the following structural format. The backend system will automatically assign new timestamps and IDs to your output.

## [Consolidated] {Topic or Theme}
{Dense, synthesized narrative of the events, facts, or decisions}
"""
        async with aiofiles.open(DREAM_PROMPT_FILE, 'w') as f:
            await f.write(prompt)

async def load_users() -> dict:
    async with global_users_lock:
        try:
            async with aiofiles.open(USERS_FILE, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except Exception:
            return {"users": {}}

async def save_users(data: dict):
    async with global_users_lock:
        async with aiofiles.open(USERS_FILE, 'w') as f:
            await f.write(json.dumps(data, indent=2))

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def get_time_str():
    return datetime.utcnow().strftime("%H:%M:%S")

def get_current_block_prefix():
    now = datetime.utcnow()
    window_hours = int(os.environ.get("ACTIVE_MEMORY_WINDOW_HOURS", "4"))
    block_start_hour = (now.hour // window_hours) * window_hours
    date_str = now.strftime("%Y-%m-%d")
    return f"{date_str}_{block_start_hour:02d}"

async def append_memory(user_id: str, content: str) -> tuple[str, str, str]:
    block_prefix = get_current_block_prefix()
    time_str = get_time_str()
    memory_id = str(uuid.uuid4())
    
    file_name = f"memory.{block_prefix}.active.md"
    file_path = os.path.join(DATA_DIR, user_id, file_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    formatted_block = f"## [{time_str}] {memory_id}\n{content.strip()}\n\n"
    
    async with get_user_lock(user_id):
        async with aiofiles.open(file_path, 'a') as f:
            await f.write(formatted_block)
            
    return memory_id, formatted_block, file_name

async def parse_memory_file(file_path: str) -> list[dict]:
    if not os.path.exists(file_path):
        return []
        
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
        
    blocks = []
    pattern = re.compile(r'^##\s+\[(.*?)\]\s+(.*?)\n(.*?)(?=\n##\s+\[|\Z)', re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(content):
        blocks.append({
            "time": match.group(1),
            "id": match.group(2).strip(),
            "content": match.group(3).strip()
        })
    return blocks

async def write_memory_file(file_path: str, blocks: list[dict]):
    out = ""
    for b in blocks:
        out += f"## [{b['time']}] {b['id']}\n{b['content']}\n\n"
    async with aiofiles.open(file_path, 'w') as f:
        await f.write(out)

async def update_memory(user_id: str, memory_id: str, new_content: str) -> tuple[bool, str]:
    user_dir = os.path.join(DATA_DIR, user_id)
    if not os.path.exists(user_dir):
        return False, ""
        
    async with get_user_lock(user_id):
        for fname in os.listdir(user_dir):
            if fname.startswith("memory.") and fname.endswith(".md"):
                file_path = os.path.join(user_dir, fname)
                blocks = await parse_memory_file(file_path)
                changed = False
                for b in blocks:
                    if b['id'] == memory_id:
                        b['content'] = new_content.strip()
                        changed = True
                        break
                if changed:
                    await write_memory_file(file_path, blocks)
                    return True, fname
    return False, ""

async def delete_memory(user_id: str, memory_id: str) -> tuple[bool, str]:
    user_dir = os.path.join(DATA_DIR, user_id)
    if not os.path.exists(user_dir):
        return False, ""
        
    async with get_user_lock(user_id):
        for fname in os.listdir(user_dir):
            if fname.startswith("memory.") and fname.endswith(".md"):
                file_path = os.path.join(user_dir, fname)
                blocks = await parse_memory_file(file_path)
                original_len = len(blocks)
                blocks = [b for b in blocks if b['id'] != memory_id]
                if len(blocks) != original_len:
                    if not blocks:
                        os.remove(file_path)
                    else:
                        await write_memory_file(file_path, blocks)
                    return True, fname
    return False, ""

async def get_active_context(user_id: str) -> str:
    # Returns all un-ingested active files contents to inject directly into the LLM context.
    user_dir = os.path.join(DATA_DIR, user_id)
    if not os.path.exists(user_dir):
        return ""
    
    context = ""
    for fname in os.listdir(user_dir):
        if fname.startswith("memory.") and fname.endswith(".active.md"):
            file_path = os.path.join(user_dir, fname)
            async with aiofiles.open(file_path, 'r') as f:
                context += f"\n--- {fname} ---\n"
                context += await f.read()
    return context.strip()
