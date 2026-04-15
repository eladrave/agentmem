# AI Agentic Memory MCP Server

A highly robust, multi-tenant, containerized Model Context Protocol (MCP) server. This server acts as the long-term cognitive memory for an AI system using a dual-layer storage approach:
1. **Local File System**: Absolute Source of Truth, mounted via a cloud bucket or docker volume.
2. **Google Gemini API**: Used for Semantic Retrieval and RAG queries (with graceful fallbacks for deprecation or API quota limits).

## Features

- **Standard MCP Tool Exposal**: Exposes `add_memory`, `search_memories`, `update_memory`, `delete_memory`, and `sync_memories` directly to any standard MCP client.
- **The "Dream" Subsystem**: A cognitive consolidation process. Mimicking sleep, it uses a heavier LLM reasoning model to deduplicate and synthesize raw daily logs into dense, high-value permanent memories.
- **Robust Storage**: Uses completely flat markdown files with async locks to prevent race conditions. Fully Cloud Run and Cloud Storage FUSE compatible.
- **Multi-Tenant Administration**: Admin endpoints to provision new isolated tenants, each with their own secure Gemini corpora and tokens.
- **Bring Your Own Key (BYOK)**: Solves the Google Gemini 10-Corpus limit by allowing each user to securely provide their own `X-Gemini-Api-Key` HTTP Header over MCP!

## Prerequisites

- **Google Cloud Project** (if deploying to cloud)
- **Google Gemini API Key** (Can be supplied per-user or globally)
- Python 3.11+ / Docker

## Getting Started

### Local Deployment via Docker

1. Clone the repository.
2. Build the Docker image:
   ```bash
   docker build -t agentic-memory-mcp .
   ```
3. Run the container:
   ```bash
   docker run -d --name agentmem \
     -p 8080:8080 \
     -e ADMIN_PASSWORD="your_secure_password" \
     -e GEMINI_API_KEY="your_global_gemini_api_key" \
     -v $(pwd)/data:/data \
     agentic-memory-mcp
   ```

### Provisioning a User

Before using the MCP Client, you must provision a user. This will securely hash credentials and return a Bearer token.

```bash
curl -X POST http://localhost:8080/admin/users \
     -H "X-Admin-Password: your_secure_password"
```

### Rotating a User Token

If you ever need to invalidate a user's current token and generate a new one, use the rotate endpoint:

```bash
curl -X POST http://localhost:8080/admin/users/<YOUR_USER_ID>/rotate \
     -H "X-Admin-Password: your_secure_password"
```

## MCP Client Configuration

Once you have provisioned a user and received a `token`, you can configure your MCP client to connect to the server.

### Standard Configuration Example

Here is a standard JSON example for configuring an MCP Client via Server-Sent Events (SSE):

```json
{
  "mcpServers": {
    "agentic_memory": {
      "transport": {
        "type": "sse",
        "url": "https://<YOUR_CLOUD_RUN_URL>/mcp/sse",
        "headers": {
          "Authorization": "Bearer <YOUR_MEM_TOKEN>",
          "X-Gemini-Api-Key": "<OPTIONAL_PERSONAL_GEMINI_KEY>"
        }
      }
    }
  }
}
```
*Note: If you omit `X-Gemini-Api-Key`, the system will default to the Cloud Run server's global environment API key. If that global key hits the 10-corpus free-tier limit, semantic searches will gracefully return a mock placeholder while continuing to store data safely in your local Storage Bucket.*

### Available Tools

Once connected, your AI agent will automatically be granted the following tools:
1.  **`add_memory(content: str)`**: Appends a new memory block to today's active file and syncs it to Gemini.
2.  **`search_memories(query: str)`**: Semantically searches all stored memories using the Gemini API.
3.  **`update_memory(memory_id: str, new_content: str)`**: Replaces the content of a specific memory block both locally and in Gemini.
4.  **`delete_memory(memory_id: str)`**: Removes a specific memory block locally and from Gemini.
5.  **`sync_memories(force_sync: bool)`**: Forces a synchronization between the local file system (Source of Truth) and the Gemini Corpus.

## Dealing with Key Rotations & Corpus Rebuilding

If a user revokes their Gemini API key or wants to move their memory vector index to a brand new remote Corpus, they simply hit the `/api/corpus/rebuild` endpoint. Because the local Markdown files are the Absolute Source of Truth, the backend will generate a new Corpus on the new Key and automatically bulk-upload all existing memories directly into it!

```bash
curl -X POST http://localhost:8080/api/corpus/rebuild \
     -H "Authorization: Bearer <YOUR_MEM_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"new_api_key": "<YOUR_NEW_GEMINI_KEY>"}'
```

## Cloud Run Deployment

Use the included interactive deploy script to automatically deploy this server to Google Cloud Run, backed by a Google Cloud Storage bucket (using GCS FUSE).

```bash
./deploy.sh
```
