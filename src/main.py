import asyncio
from fastapi import FastAPI, Depends, HTTPException, Request, Header, BackgroundTasks, Response
from starlette.responses import StreamingResponse
from pydantic import BaseModel
import uuid
from typing import Optional
from src import storage, gemini_service
import os
import aiofiles
from datetime import datetime, timedelta

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "secret")

app = FastAPI(title="AI Agentic Memory MCP Server")

@app.on_event("startup")
async def startup():
    await storage.init_storage()

def verify_admin(authorization: str = Header(None), x_admin_password: str = Header(None)):
    token = x_admin_password
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

async def verify_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    token = authorization[7:]
    hashed = storage.hash_token(token)
    users_data = await storage.load_users()
    for uid, udata in users_data.get("users", {}).items():
        if hashed in udata.get("tokens", {}):
            if udata["tokens"][hashed]["status"] == "active":
                return {"user_id": uid, "corpus_id": udata["gemini_corpus_id"]}
    raise HTTPException(status_code=401, detail="Invalid or revoked token")

class UserResponse(BaseModel):
    user_id: str
    token: str

@app.post("/admin/users", response_model=UserResponse)
async def create_user(admin=Depends(verify_admin)):
    user_id = str(uuid.uuid4())
    raw_token = "mem_" + str(uuid.uuid4()).replace("-", "")
    hashed = storage.hash_token(raw_token)
    corpus_id = await gemini_service.create_corpus(f"Memory Corpus for {user_id}")
    users_data = await storage.load_users()
    users_data["users"][user_id] = {
        "gemini_corpus_id": corpus_id,
        "tokens": {
            hashed: {
                "status": "active",
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
        }
    }
    await storage.save_users(users_data)
    user_dir = os.path.join(storage.DATA_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    return UserResponse(user_id=user_id, token=raw_token)

@app.post("/admin/users/{user_id}/rotate", response_model=UserResponse)
async def rotate_user(user_id: str, admin=Depends(verify_admin)):
    users_data = await storage.load_users()
    if user_id not in users_data.get("users", {}):
        raise HTTPException(status_code=404, detail="User not found")
    for t_hash in users_data["users"][user_id]["tokens"]:
        users_data["users"][user_id]["tokens"][t_hash]["status"] = "revoked"
    raw_token = "mem_" + str(uuid.uuid4()).replace("-", "")
    hashed = storage.hash_token(raw_token)
    users_data["users"][user_id]["tokens"][hashed] = {
        "status": "active",
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    await storage.save_users(users_data)
    return UserResponse(user_id=user_id, token=raw_token)

async def sync_user_memories(user_id: str, corpus_id: str, force: bool):
    user_dir = os.path.join(storage.DATA_DIR, user_id)
    if not os.path.exists(user_dir): return
    local_files = [f for f in os.listdir(user_dir) if f.startswith("memory.") and f.endswith(".md")]
    if force:
        docs = await gemini_service.list_documents(corpus_id)
        for doc in docs:
            await gemini_service.delete_document(doc["name"])
    for fname in local_files:
        file_path = os.path.join(user_dir, fname)
        blocks = await storage.parse_memory_file(file_path)
        doc_name = await gemini_service.get_or_create_document(corpus_id, fname)
        remote_chunks = await gemini_service.list_chunks(doc_name)
        remote_map = {}
        for rc in remote_chunks:
            mid = None
            if rc.get("customMetadata"):
                for m in rc["customMetadata"]:
                    if m.get("key") == "memory_id": mid = m.get("stringValue")
            if mid: remote_map[mid] = rc
        local_map = {b['id']: b for b in blocks}
        for mid, b in local_map.items():
            if mid not in remote_map:
                await gemini_service.create_chunk(doc_name, b['content'], mid)
        for mid, rc in remote_map.items():
            if mid not in local_map:
                await gemini_service.delete_chunk(corpus_id, fname, mid)

import re

async def process_dream_output(user_id: str, corpus_id: str, target_date: str, raw_output: str):
    user_dir = os.path.join(storage.DATA_DIR, user_id)
    post_file = os.path.join(user_dir, f"memory.{target_date}.postdream.md")
    blocks = []
    parts = re.split(r'^##\s+\[', raw_output, flags=re.MULTILINE)
    for part in parts:
        if not part.strip(): continue
        lines = part.split("\n", 1)
        header = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else ""
        mid = str(uuid.uuid4())
        blocks.append({
            "time": "Consolidated",
            "id": mid,
            "content": f"Topic: {header}\n{content}"
        })
        
    async with storage.get_user_lock(user_id):
        await storage.write_memory_file(post_file, blocks)
        
    docs = await gemini_service.list_documents(corpus_id)
    for doc in docs:
        dname = doc.get("displayName", "")
        if dname == f"memory.{target_date}.md" or dname == f"memory.{target_date}.postdream.md":
            await gemini_service.delete_document(doc["name"])
            
    doc_name = await gemini_service.get_or_create_document(corpus_id, f"memory.{target_date}.postdream.md")
    for b in blocks:
        await gemini_service.create_chunk(doc_name, b['content'], b['id'])

async def run_dream_for_user(user_id: str, corpus_id: str, target_date: str):
    user_dir = os.path.join(storage.DATA_DIR, user_id)
    md_file = os.path.join(user_dir, f"memory.{target_date}.md")
    post_file = os.path.join(user_dir, f"memory.{target_date}.postdream.md")
    
    combined_text = ""
    if os.path.exists(md_file):
        async with aiofiles.open(md_file, 'r') as f:
            combined_text += await f.read() + "\n"
    if os.path.exists(post_file):
        async with aiofiles.open(post_file, 'r') as f:
            combined_text += await f.read() + "\n"
            
    if not combined_text.strip(): return
        
    async with aiofiles.open(storage.DREAM_PROMPT_FILE, 'r') as f:
        prompt = await f.read()
        
    new_content = await gemini_service.generate_dream(prompt, combined_text)
    
    if os.path.exists(md_file):
        os.remove(md_file)
        
    await process_dream_output(user_id, corpus_id, target_date, new_content)

class DreamRequest(BaseModel):
    target_date: Optional[str] = None

@app.post("/api/dream")
async def api_dream(req: DreamRequest = None, user_info=Depends(verify_user)):
    target_date = req.target_date if req and req.target_date else (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    await run_dream_for_user(user_info["user_id"], user_info["corpus_id"], target_date)
    return {"status": "success", "target_date": target_date}

@app.post("/admin/dream_all", status_code=202)
async def admin_dream_all(background_tasks: BackgroundTasks, admin=Depends(verify_admin)):
    target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    async def run_all():
        users_data = await storage.load_users()
        for uid, udata in users_data.get("users", {}).items():
            corpus_id = udata.get("gemini_corpus_id")
            if corpus_id:
                try:
                    await run_dream_for_user(uid, corpus_id, target_date)
                except Exception as e:
                    print(f"Dream failed for {uid}: {e}")
    background_tasks.add_task(run_all)
    return {"status": "accepted"}

# --- MCP INTEGRATION ---

sse_transport = SseServerTransport("/mcp/messages/")

# We mount the endpoints using Starlette's Mount/Route to avoid FastAPI intercepting the response lifecycle 
# exactly the way FastMCP does.
from starlette.routing import Route, Mount
from starlette.middleware import Middleware
from starlette.responses import Response

async def handle_sse(request: Request) -> Response:
    # Authenticate manually since this is a Starlette endpoint, not a FastAPI route
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return Response("Unauthorized", status_code=401)
        
    token = auth_header[7:]
    hashed = storage.hash_token(token)
    users_data = await storage.load_users()
    
    user_info = None
    for uid, udata in users_data.get("users", {}).items():
        if hashed in udata.get("tokens", {}):
            if udata["tokens"][hashed]["status"] == "active":
                user_info = {"user_id": uid, "corpus_id": udata["gemini_corpus_id"]}
                break
                
    if not user_info:
        return Response("Unauthorized", status_code=401)

    server = Server(f"memory-{user_info['user_id']}")
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name="add_memory", description="Append a new timestamped block to today's memory", inputSchema={"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}),
            Tool(name="search_memories", description="Query the Gemini Retriever API", inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
            Tool(name="update_memory", description="Replace a text block locally and in Gemini", inputSchema={"type": "object", "properties": {"memory_id": {"type": "string"}, "new_content": {"type": "string"}}, "required": ["memory_id", "new_content"]}),
            Tool(name="delete_memory", description="Delete a text block locally and in Gemini", inputSchema={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]}),
            Tool(name="sync_memories", description="Sync local chunks with Gemini", inputSchema={"type": "object", "properties": {"force_sync": {"type": "boolean", "default": False}}})
        ]
        
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        user_id = user_info['user_id']
        corpus_id = user_info['corpus_id']
        
        try:
            if name == "add_memory":
                memory_id, _, date_str = await storage.append_memory(user_id, arguments["content"])
                await gemini_service.update_chunk(corpus_id, f"memory.{date_str}.md", memory_id, arguments["content"])
                return [TextContent(type="text", text=f"Added memory {memory_id}")]
            elif name == "search_memories":
                results = await gemini_service.search_corpus(corpus_id, arguments["query"])
                return [TextContent(type="text", text="Search Results:\n" + "\n".join(results))]
            elif name == "update_memory":
                success = await storage.update_memory(user_id, arguments["memory_id"], arguments["new_content"])
                if success:
                    await sync_user_memories(user_id, corpus_id, force=False)
                    return [TextContent(type="text", text=f"Updated memory {arguments['memory_id']}")]
                return [TextContent(type="text", text=f"Memory {arguments['memory_id']} not found")]
            elif name == "delete_memory":
                success = await storage.delete_memory(user_id, arguments["memory_id"])
                if success:
                    await sync_user_memories(user_id, corpus_id, force=False)
                    return [TextContent(type="text", text=f"Deleted memory {arguments['memory_id']}")]
                return [TextContent(type="text", text=f"Memory {arguments['memory_id']} not found")]
            elif name == "sync_memories":
                await sync_user_memories(user_id, corpus_id, force=arguments.get("force_sync", False))
                return [TextContent(type="text", text="Sync completed")]
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())
    return Response()

app.routes.append(Route("/mcp/sse", endpoint=handle_sse, methods=["GET"]))
app.routes.append(Mount("/mcp/messages/", app=sse_transport.handle_post_message))

