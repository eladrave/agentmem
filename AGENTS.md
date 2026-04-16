# Agent Interaction Guide (AGENTS.md)

This document is designed to be read by LLMs (like Claude, GPT-4, etc.) acting as autonomous agents via the Model Context Protocol (MCP). It explains how the Agentic Memory Server functions under the hood so you can use its tools effectively.

## Architecture: The L1 / L2 Cache
This server does not use a traditional, brittle vector database. It uses a highly resilient dual-layer caching system:

1. **L1 Cache (Active Local Memory):** 
   When you call `add_memory`, your memory is written to a local Markdown file on the server (e.g., `memory.2026-04-16_12.active.md`). This allows you to add memories as fast as you want without triggering remote API rate limits.
2. **L2 Cache (Ingested Remote Memory):** 
   Once a time window passes (default 4 hours) or when `sync_memories(force_sync=True)` is called, the server seals the `.active.md` file, renames it to `.ingested.md`, and physically uploads the text file to Google Gemini's File API.
3. **Retrieval-Augmented Generation (RAG):**
   When you call `search_memories`, the server does **not** return raw JSON chunks. It scoops up the user's uploaded memory files, attaches them directly into a `gemini-2.5-flash` context window, and prompts Gemini to read the files and return a conversational, highly accurate answer.

## Tool Usage Best Practices

1. **`add_memory(content: str)`**
   - **Do:** Use this to store facts, user preferences, and important context. 
   - **Don't:** Do not call `sync_memories` immediately after this! The server automatically injects your freshly added (L1) active memories into the LLM prompt during searches. It is instantly available.

2. **`search_memories(query: str)`**
   - **Do:** Ask natural language questions like *"What is the user's son's name?"* or *"What are the user's preferred coding frameworks?"*
   - **Note:** The response will be a synthesized, human-readable answer directly from Gemini, reading the raw Markdown files.

3. **`update_memory(memory_id: str, new_content: str)`** & **`delete_memory(memory_id: str)`**
   - **Do:** Use these when a user changes their mind (e.g., *"Actually, my dog's name is Max now"*).
   - **Behind the scenes:** If the memory is in the L2 cache, the server will automatically delete the old file from Gemini and upload the newly corrected file. This takes a few seconds.

4. **`sync_memories(force_sync: bool)`**
   - **Do NOT** call this routinely. The server's background logic handles time-windowed ingestion automatically during `add` and `search` operations. 
   - Only use `force_sync=True` if you explicitly suspect the remote Gemini File API has fallen out of sync with the server's local Source of Truth (the `/data` directory).

## The "Dream" Subsystem
Every night (or when manually triggered via API), the server runs a heavy reasoning model (`gemini-2.5-pro`) over all the raw, timestamped `.md` files. It deduplicates them, removes conversational filler, resolves chronological conflicts, and condenses them into a single `memory.YYYY-MM-DD.postdream.md` file. This prevents the memory context window from blowing up over months of usage.
