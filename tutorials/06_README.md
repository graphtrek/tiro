# Tutorial 06: PostgreSQL Direct Backend (Phase 1)

## Overview

**Phase 1: Core Agent Script** — A standalone backend Python script that demonstrates how to build a production-like PostgreSQL assistant using a local LLM (gemma4:e4b) with direct SQL execution.

The script implements a **tool-calling agent loop**: the LLM discovers database schema and generates/executes SQL queries in response to natural language questions.

## Key Features

✅ **Local LLM Integration** — Uses gemma4:e4b via Ollama on `http://localhost:1234/v1`  
✅ **Agent Loop** — Full OpenAI function-calling pattern with tool execution  
✅ **Schema Discovery** — LLM can list tables, describe columns, sample data  
✅ **SQL Generation & Execution** — LLM generates SELECT queries, executes them, interprets results  
✅ **Execution Timing** — Tracks and logs query performance  
✅ **Direct psycopg2** — Standalone implementation, no dependencies on nothing-gets-out  
✅ **Interactive CLI** — Loop for user queries with real-time responses  

## Requirements

### 1. Local LLM (Ollama)

```bash
# Install Ollama (if not already installed)
# https://ollama.ai

# Start the local LLM
ollama run gemma4:e4b
# Listens on http://localhost:1234/v1
```

### 2. PostgreSQL Database

Set environment variables (or create `.env`):

```bash
# Option A: Full connection URL
MONEYPENNY_DB_URL="postgresql://user:password@localhost:5432/moneypenny"

# Option B: Components (legacy)
MONEYPENNY_DB_USER=your_username
MONEYPENNY_DB_PWD=your_password
UM_DB_URL="postgresql://localhost:5432/moneypenny"
```

### 3. Python Dependencies

```bash
pip install openai python-dotenv psycopg2
```

That's it! This script is completely standalone with no dependencies on other projects.

## How to Run

```bash
cd tutorials

# Start the interactive agent
python 06_postgres_direct.py
```

You'll see:

```
================================================================================
PostgreSQL Direct Backend Tutorial
================================================================================

Local LLM Agent with Database Access
Model: gemma4:e4b
Endpoint: http://localhost:1234/v1

Enter natural language questions about the database.
Type 'exit' to quit.

You: 
```

## Example Queries

Try these to explore the agent's capabilities:

### 1. Discover Schema
```
You: What tables exist in the database?
```

Agent response:
- Calls `get_schema_info()` to list all tables
- Returns table names, column counts, estimated row counts

### 2. Table Structure
```
You: Show me the structure of the customers table
```

Agent response:
- Calls `describe_table("customers")`
- Returns columns, data types, nullable flags, primary keys

### 3. Sample Data
```
You: Show me 5 customers
```

Agent response:
- Calls `get_table_sample("customers", limit=5)`
- Returns sample rows for inspection

### 4. Analytical Query
```
You: How many orders are there in total?
```

Agent response:
- Discovers schema first
- Generates SQL: `SELECT COUNT(*) as total_orders FROM orders`
- Executes query and interprets results

### 5. Complex Analysis
```
You: What are the top 5 customers by revenue?
```

Agent response:
- Explores schema to understand customer and order relationships
- Generates JOIN query
- Executes and explains results

## Architecture

### Tool Execution Flow

```
User Query
    ↓
LLM (with system prompt + tools)
    ↓
Tool Calls (JSON)
    ↓
execute_tool() — routes to postgres_service or fallback
    ↓
Tool Result (JSON)
    ↓
Feed back to LLM
    ↓
(repeat until finish_reason != "tool_calls")
    ↓
Final Response
```

### Tool Definitions (5 functions)

| Tool | Purpose |
|------|---------|
| `get_schema_info()` | Full database schema overview |
| `list_tables()` | List base tables in schema |
| `describe_table()` | Column details + metadata |
| `get_table_sample()` | Sample rows from table |
| `execute_query()` | Execute SELECT query (max 200 rows) |

### postgres_service Integration

This script is completely **standalone** — it uses direct psycopg2 without depending on the nothing-gets-out project.

All 5 tool functions are implemented natively in the `_execute_tool_fallback()` function:

- `get_schema_info()` — Queries `information_schema` tables for schema overview
- `list_tables()` — Lists base tables in public schema
- `list_views()` — Lists views
- `describe_table()` — Gets column metadata + row count from `pg_class`
- `get_table_sample()` — Returns sample rows with `LIMIT`
- `execute_query()` — Executes SELECT queries with `statement_timeout` and security checks

## Configuration (Environment Variables)

```bash
# LLM Configuration
OLLAMA_BASE_URL=http://localhost:1234/v1  # Local Ollama endpoint
OLLAMA_API_KEY=not-needed-for-ollama      # Placeholder (not used by Ollama)
LOCAL_LLM_MODEL=gemma4:e4b                # Model name

# PostgreSQL Configuration
MONEYPENNY_DB_URL=postgresql://...        # Full connection string
# OR
UM_DB_URL=postgresql://localhost:5432/moneypenny
MONEYPENNY_DB_USER=your_user
MONEYPENNY_DB_PWD=your_password
```

## Logging

The script logs at `INFO` level to console:

```
[packages.database.postgres_service] INFO: Executing tool: list_tables with args: {'schema': 'public'}
[__main__] INFO: Agent round 1
[__main__] INFO: Tool call: list_tables
[__main__] INFO: Tool executed in 45.3ms
[__main__] INFO: Agent round 2
[__main__] INFO: Agent completed (no more tool calls)
```

Control logging level:

```python
logging.basicConfig(level=logging.DEBUG)  # For verbose output
```

## Troubleshooting

### "Connection refused" error
- Ensure PostgreSQL is running and accessible
- Check `MONEYPENNY_DB_URL` or connection components are correct
- Test connection: `psql postgresql://user:password@host:port/db`

### "Model not found" error
- Ensure Ollama is running: `ollama run gemma4:e4b`
- Check `OLLAMA_BASE_URL` (default: `http://localhost:1234/v1`)

### Agent exceeds max tool calls
- Try a simpler question
- Increase `max_tool_rounds = 10` (in code) if needed
- Check agent logs for tool execution errors

## Next Steps

This is **Phase 1 of a 3-part tutorial series**:

1. **Phase 1** (this script) — Core agent loop with direct SQL execution
2. **Phase 2** (coming) — MCP Server wrapper for VS Code Copilot integration
3. **Phase 3** (coming) — FastAPI manager service for multi-instance orchestration

See the plan in `/memories/session/plan.md` for details.

## References

- [OpenAI Python SDK](https://github.com/openai/openai-python) — Tool-calling patterns
- [PostgreSQL information_schema](https://www.postgresql.org/docs/current/information_schema.html) — Schema introspection
- [Ollama](https://ollama.ai) — Local LLM hosting
