#!/usr/bin/env python3
# =============================================================================
# 06_postgres_direct.py — Backend Tutorial: Local LLM + PostgreSQL Agent Loop
#
# Purpose:
#   Demonstrates how to build a production-like PostgreSQL assistant with
#   a local LLM (gemma4:e4b). The agent discovers database schema and
#   generates/executes SQL queries in response to natural language questions.
#   Completely standalone with no dependencies on other projects.
#
# Requirements:
#   1. Local LLM: Run `ollama run gemma4:e4b` (listens on http://localhost:1234/v1)
#   2. PostgreSQL: Set environment variables or .env:
#      - MONEYPENNY_DB_URL (full connection string)
#   3. Python dependencies: openai, python-dotenv, psycopg2
#
# How to run:
#   ```
#   cd tutorials
#   python 06_postgres_direct.py
#   ```
#   Then enter natural language questions at the prompt.
#
# Example queries:
#   - "What tables exist in the database?"
#   - "Show me the structure of the customers table"
#   - "How many orders are there in total?"
#   - "What are the top 5 customers by revenue?"
#
# =============================================================================

import json
import logging
import os
import sys
import time
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

# No dependencies on nothing-gets-out project
# This tutorial is completely standalone using direct psycopg2

# =============================================================================
# Setup & Configuration
# =============================================================================

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client for local gemma4:e4b
LOCAL_LLM_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:1234/v1")
LOCAL_LLM_API_KEY = os.environ.get("OLLAMA_API_KEY", "not-needed-for-ollama")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")

client = OpenAI(base_url=LOCAL_LLM_BASE_URL, api_key=LOCAL_LLM_API_KEY)

logger.info(f"Connected to local LLM at {LOCAL_LLM_BASE_URL}")
logger.info(f"Model: {LOCAL_LLM_MODEL}")

# =============================================================================
# Tool Definitions (OpenAI function-calling schema)
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_schema_info",
            "description": (
                "Return a full overview of the database schema: all tables with column counts "
                "and estimated row counts. Call this first when exploring an unfamiliar database."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "schema": {"type": "string", "description": "PostgreSQL schema name (default: 'public')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List all base tables in the given PostgreSQL schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema": {"type": "string", "description": "PostgreSQL schema name (default: 'public')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": (
                "Return column names, data types, nullable flag, default value, and primary key "
                "information for a specific table, plus an estimated row count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "Name of the table to describe"},
                    "schema": {"type": "string", "description": "PostgreSQL schema name (default: 'public')"},
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_sample",
            "description": "Return a sample of rows from a table (up to 100 rows).",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string", "description": "Name of the table to sample"},
                    "limit": {"type": "integer", "description": "Number of rows to return (1-100, default 5)"},
                    "schema": {"type": "string", "description": "PostgreSQL schema name (default: 'public')"},
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_query",
            "description": (
                "Execute a read-only SELECT query against the database and return up to 200 rows. "
                "Only SELECT statements are permitted; any other SQL will be rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A valid SELECT SQL statement (no semicolon at the end)"},
                },
                "required": ["sql"],
            },
        },
    },
]

# =============================================================================
# Helper Functions
# =============================================================================

def _convert_decimals_to_strings(obj):
    """
    Recursively convert Decimal objects to strings for JSON serialization.
    PostgreSQL returns Decimal types which are not JSON serializable.
    """
    from decimal import Decimal
    
    if isinstance(obj, dict):
        return {k: _convert_decimals_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_decimals_to_strings(item) for item in obj]
    elif isinstance(obj, Decimal):
        return str(obj)
    return obj

# =============================================================================
# Tool Execution
# =============================================================================

def execute_tool(tool_name: str, tool_args: dict) -> dict:
    """
    Execute a database tool by name and return results using direct psycopg2.
    
    Tools: get_schema_info, list_tables, describe_table, get_table_sample, execute_query
    """
    import psycopg2
    import psycopg2.extras
    
    start_time = time.time()
    
    try:
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
        # Build connection string from environment
        db_url = os.environ.get("MONEYPENNY_DB_URL")
        if not db_url:
            return {"error": "MONEYPENNY_DB_URL not set in environment"}
        
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        result = None
        
        if tool_name == "get_schema_info":
            schema = tool_args.get("schema", "public")
            sql = """
                SELECT
                    t.table_name,
                    t.table_type,
                    COUNT(c.column_name) AS column_count,
                    COALESCE(s.n_live_tup, 0) AS estimated_rows
                FROM information_schema.tables t
                JOIN information_schema.columns c
                    ON t.table_name = c.table_name AND t.table_schema = c.table_schema
                LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
                WHERE t.table_schema = %s
                GROUP BY t.table_name, t.table_type, s.n_live_tup
                ORDER BY t.table_name
            """
            cur.execute(sql, (schema,))
            tables = [dict(row) for row in cur.fetchall()]
            result = {"schema": schema, "tables": tables}
        
        elif tool_name == "list_tables":
            schema = tool_args.get("schema", "public")
            sql = """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
            cur.execute(sql, (schema,))
            result = [dict(row) for row in cur.fetchall()]
        
        elif tool_name == "list_views":
            schema = tool_args.get("schema", "public")
            sql = """
                SELECT table_name AS view_name
                FROM information_schema.views
                WHERE table_schema = %s
                ORDER BY table_name
            """
            cur.execute(sql, (schema,))
            result = [dict(row) for row in cur.fetchall()]
        
        elif tool_name == "describe_table":
            schema = tool_args.get("schema", "public")
            table = tool_args.get("table_name")
            sql = """
                SELECT
                    c.column_name, c.data_type, c.is_nullable, c.column_default,
                    CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key
                FROM information_schema.columns c
                LEFT JOIN (
                    SELECT kcu.column_name FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = %s AND tc.table_name = %s
                ) pk ON c.column_name = pk.column_name
                WHERE c.table_schema = %s AND c.table_name = %s
                ORDER BY c.ordinal_position
            """
            cur.execute(sql, (schema, table, schema, table))
            columns = [dict(row) for row in cur.fetchall()]
            
            if not columns:
                result = {"error": f"Table '{schema}.{table}' not found"}
            else:
                # Get estimated row count
                sql_rows = "SELECT reltuples::bigint AS estimated_rows FROM pg_class WHERE relname = %s"
                cur.execute(sql_rows, (table,))
                row = cur.fetchone()
                estimated_rows = row["estimated_rows"] if row else None
                
                result = {
                    "table": f"{schema}.{table}",
                    "columns": columns,
                    "estimated_rows": estimated_rows,
                }
        
        elif tool_name == "get_table_sample":
            table = tool_args.get("table_name")
            limit = max(1, min(int(tool_args.get("limit", 5)), 100))
            schema = tool_args.get("schema", "public")
            
            # Validate identifiers
            if not table.replace("_", "").isalnum():
                result = {"error": "Invalid table name"}
            else:
                safe_schema = schema if schema.replace("_", "").isalnum() else "public"
                query = f'SELECT * FROM "{safe_schema}"."{table}" LIMIT {limit}'
                cur.execute(query)
                rows = [dict(row) for row in cur.fetchall()]
                cols = [desc[0] for desc in cur.description] if cur.description else []
                result = {"query": query, "columns": cols, "rows": rows, "count": len(rows)}
        
        elif tool_name == "execute_query":
            sql = tool_args.get("sql", "").strip()
            upper = sql.upper()
            
            # Security: only SELECT or WITH queries allowed
            if not (upper.startswith("SELECT") or upper.startswith("WITH")):
                result = {"error": "Only SELECT queries are allowed"}
            elif ";" in sql:
                result = {"error": "Multiple statements are not allowed; remove the semicolon"}
            else:
                # Execute query with timeout
                cur.execute("SET statement_timeout = '60000'")
                cur.execute(sql)
                rows = [dict(row) for row in cur.fetchmany(200)]
                cols = [desc[0] for desc in cur.description] if cur.description else []
                result = {"query": sql, "columns": cols, "rows": rows, "count": len(rows)}
        
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        
        # Convert Decimals to strings for JSON serialization
        result = _convert_decimals_to_strings(result)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"Tool executed in {elapsed_ms:.1f}ms")
        
        return result
    
    except Exception as e:
        err_str = str(e)
        is_timeout = "statement timeout" in err_str.lower() or "canceling statement" in err_str.lower()
        logger.error(f"Tool execution error: {e}", exc_info=True)
        return {"error": err_str, "timeout": is_timeout}
    
    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

# =============================================================================
# Main Agent Loop
# =============================================================================

SYSTEM_PROMPT = """You are a helpful PostgreSQL database assistant. Your role is to help users explore and query a PostgreSQL database.

You have access to tools that let you:
1. Discover the database schema (get_schema_info, list_tables, describe_table)
2. Sample data from tables (get_table_sample)
3. Execute SQL queries (execute_query)

When a user asks a question:
1. Start by exploring the schema if you don't know the structure
2. Use describe_table to understand columns and data types
3. Use get_table_sample to see example data
4. Generate a SELECT query that answers the user's question
5. Execute the query and explain the results

Always:
- Use read-only SELECT queries
- Explain what you're doing and why
- Show query results in a clear, understandable format
- Ask for clarification if the question is ambiguous
"""


def run_agent_loop(user_query: str) -> str:
    """
    Run the main agent loop: LLM + tool calling until completion.
    
    Returns the final response text.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]
    
    tool_rounds = 0
    max_tool_rounds = 10
    
    while tool_rounds < max_tool_rounds:
        tool_rounds += 1
        logger.info(f"Agent round {tool_rounds}")
        
        # Call LLM with tools
        response = client.chat.completions.create(
            model=LOCAL_LLM_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",  # Let the model decide whether to use tools
            temperature=0.0,
            max_tokens=4096,
        )
        
        finish_reason = response.choices[0].finish_reason
        assistant_message = response.choices[0].message
        
        # Check if we're done (no more tool calls)
        if finish_reason == "end_turn" or finish_reason == "stop":
            # Extract final text response
            final_text = assistant_message.content or ""
            logger.info("Agent completed (no more tool calls)")
            return final_text
        
        if finish_reason == "tool_calls" and assistant_message.tool_calls:
            # Add assistant's message (with content and tool_calls) to history
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_message.tool_calls
                ],
            })
            
            # Execute each tool call
            for tool_call in assistant_message.tool_calls:
                fn_name = tool_call.function.name
                logger.info(f"Tool call: {fn_name}")
                
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}
                
                # Execute tool
                tool_result = execute_tool(fn_name, fn_args)
                
                # Add tool result to messages
                messages.append({
                    "role": "user",
                    "content": json.dumps(tool_result, indent=2),
                })
        else:
            # Unexpected finish_reason; extract what we got and return
            logger.warning(f"Unexpected finish_reason: {finish_reason}")
            final_text = assistant_message.content or ""
            return final_text
    
    # Max rounds reached
    return "⚠️ Agent exceeded maximum tool calls. Please try a simpler question."


# =============================================================================
# Interactive CLI
# =============================================================================

def main():
    """Run the interactive PostgreSQL agent."""
    print("=" * 80)
    print("PostgreSQL Direct Backend Tutorial")
    print("=" * 80)
    print()
    print("Local LLM Agent with Database Access")
    print(f"Model: {LOCAL_LLM_MODEL}")
    print(f"Endpoint: {LOCAL_LLM_BASE_URL}")
    print()
    print("Enter natural language questions about the database.")
    print("Type 'exit' to quit.")
    print()
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["exit", "quit", "bye"]:
                print("Goodbye!")
                break
            
            print()
            print("🤔 Thinking...")
            start_time = time.time()
            
            response = run_agent_loop(user_input)
            
            elapsed = time.time() - start_time
            
            print()
            print("Assistant:")
            print("-" * 80)
            print(response)
            print("-" * 80)
            print(f"⏱️  Completed in {elapsed:.1f}s")
            print()
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            print()


if __name__ == "__main__":
    main()
