# CLAUDE.md

This is **CogniRepo** — a local, protocol-agnostic cognitive infrastructure layer for AI agents.

Before doing anything, read `ARCHITECTURE.md` for the full system design, folder structure, and component responsibilities.

## What this repo is

A local memory and context engine that any AI tool (Claude, Gemini, Copilot, Cursor, Codex) can plug into. It provides semantic memory (FAISS), episodic logging, a knowledge graph, and a repo AST index — all behind a single `tools/` layer that MCP, REST, and gRPC adapters wrap.

## Key rules

- `tools/` is the single source of truth. MCP server, FastAPI, and gRPC are thin wrappers around it — never duplicate logic in an adapter.
- All storage lives under `.cognirepo/` in the project root. Never write outside it.
- The complexity classifier in `orchestrator/classifier.py` decides which model handles a query — do not hardcode model names anywhere else.
- Hybrid retrieval (`retrieval/hybrid.py`) combines FAISS + knowledge graph + behaviour weights. Do not call FAISS directly from tools.

## Commands

```bash
cognirepo init                  # scaffold .cognirepo/ and config
cognirepo index-repo [path]     # AST-index a codebase
cognirepo store-memory <text>   # save a semantic memory
cognirepo retrieve-memory <q>   # similarity search
cognirepo search-docs <q>       # search indexed docs
and others 
```

## Stack

Python 3.11 · FastAPI · FAISS · NetworkX · sentence-transformers · MCP SDK · gRPC

