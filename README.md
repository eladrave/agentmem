# AI Agentic Memory MCP Server

A highly robust, multi-tenant, containerized Model Context Protocol (MCP) server. This server acts as the long-term cognitive memory for an AI system using a dual-layer storage approach:
1. **Local File System**: Absolute Source of Truth, mounted via a cloud bucket or docker volume.
2. **Google Gemini Semantic Retriever API**: Used as the vector/RAG search engine for semantic queries.

## Features

- **Standard MCP Tool Exposal**: Exposes `add_memory`, `search_memories`, `update_memory`, `delete_memory`, and `sync_memories` directly to any standard MCP client.
- **The "Dream" Subsystem**: A cognitive consolidation process. Mimicking sleep, it uses a heavier LLM reasoning model to deduplicate and synthesize raw daily logs into dense, high-value permanent memories.
- **Robust Storage**: Uses completely flat markdown files with async locks to prevent race conditions. Fully Cloud Run and Cloud Storage FUSE compatible.
- **Multi-Tenant Administration**: Admin endpoints to provision new isolated tenants, each with their own secure Gemini corpora and tokens.

## Prerequisites

- **Google Cloud Project** (if deploying to cloud)
- **Google Gemini API Key**
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
     -e GEMINI_API_KEY="your_gemini_api_key" \
     -v $(pwd)/data:/data \
     agentic-memory-mcp
   ```

### Provisioning a User

Before using the MCP Client, you must provision a user. This will create a Gemini Corpus and return a Bearer token.

```bash
curl -X POST http://localhost:8080/admin/users \
     -H "X-Admin-Password: your_secure_password"
```

Save the `token` returned in the response.

### Connecting via MCP Client

Use the standard Server-Sent Events (SSE) configuration in your MCP Client.

- **URL**: `http://localhost:8080/mcp/sse`
- **Headers**: 
  - `Authorization`: `Bearer <YOUR_TOKEN>`

## Triggering the "Dream" Cycle

You can manually trigger the consolidation engine for a user via their token:

```bash
curl -X POST http://localhost:8080/api/dream \
     -H "Authorization: Bearer <YOUR_TOKEN>"
```

Or trigger for all users at once via Admin auth (runs in the background):

```bash
curl -X POST http://localhost:8080/admin/dream_all \
     -H "X-Admin-Password: your_secure_password"
```

## Cloud Run Deployment

Use the included interactive deploy script to automatically deploy this server to Google Cloud Run, backed by a Google Cloud Storage bucket (using GCS FUSE).

```bash
./deploy.sh
```

The script will:
1. List available GCP projects and let you select one.
2. Create a GCS Bucket for permanent state.
3. Deploy the container to Cloud Run with GCS FUSE mounted at `/data`.
4. Output your `ADMIN_PASSWORD` securely.

### Rotating a User Token

If you ever need to invalidate a user's current token and generate a new one, use the rotate endpoint:

```bash
curl -X POST http://localhost:8080/admin/users/<YOUR_USER_ID>/rotate \
     -H "X-Admin-Password: your_secure_password"
```
This sets the old token's status to `revoked` and returns a fresh `mem_...` token for immediate use.

## MCP Client Configuration

Once you have provisioned a user and received a `token`, you can configure your MCP client to connect to the server.

### Standard Configuration Example

Here is an example configuration for connecting an MCP Client via Server-Sent Events (SSE):

```json
{
  "mcpServers": {
    "agentic_memory": {
      "command": "curl",
      "args": [],
      "transport": {
        "type": "sse",
        "url": "https://<YOUR_CLOUD_RUN_URL>/mcp/sse",
        "headers": {
          "Authorization": "Bearer <YOUR_MEM_TOKEN>"
        }
      }
    }
  }
}
```

*Note: Depending on your specific MCP Client (e.g., Claude Desktop, Cursor, or a custom implementation), the exact JSON structure for configuring an SSE transport might vary slightly. Ensure you specify the transport type as `sse`, provide the full URL to the `/mcp/sse` endpoint, and include the `Authorization` header with your Bearer token.*

### Available Tools

Once connected, your AI agent will have access to the following tools:

1.  **`add_memory(content: str)`**: Appends a new memory block to today's active file and syncs it to Gemini.
2.  **`search_memories(query: str)`**: Semantically searches all stored memories using the Gemini Retriever API.
3.  **`update_memory(memory_id: str, new_content: str)`**: Replaces the content of a specific memory block both locally and in Gemini.
4.  **`delete_memory(memory_id: str)`**: Removes a specific memory block locally and from Gemini.
5.  **`sync_memories(force_sync: bool)`**: Forces a synchronization between the local file system (Source of Truth) and the Gemini Corpus.
