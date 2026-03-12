# Cognirepo

> Making repositories cognitively accessible to AI agents.

**Cognirepo** is a local cognitive infrastructure layer for AI coding agents. It provides persistent repository intelligence—including semantic memory, documentation retrieval, and contextual knowledge—so agents no longer need to repeatedly consume large token contexts.

The goal is to transform codebases from static folders into **queryable knowledge systems**.

---

## Why Cognirepo?

Current agentic workflows often send large portions of a repository to an LLM repeatedly. This "brute-force" context injection results in:

* **High Token Usage:** Expensive and inefficient.
* **Slow Reasoning:** Larger contexts increase processing time.
* **Loss of Historical Context:** Agents often "forget" previous fixes or experiments.
* **Limited Project Awareness:** Difficulty grasping the "big picture" of complex architectures.

Cognirepo introduces a **local memory and retrieval layer** that agents query *before* interacting with an LLM.

### The Impact
* **Smaller Prompts:** Only the most relevant context is sent.
* **Persistent Knowledge:** Knowledge stays local and reusable.
* **Faster Reasoning:** Reduced noise allows the model to focus on the task.
* **Improved Understanding:** Better situational awareness for the agent.

---

## Core Idea

### Traditional Workflow
`Agent` → `Send large code context` → `LLM`

### Cognirepo Workflow
`Agent`  
  ↓  
`Cognirepo MCP Tools`  
  ↓  
`Relevant Repository Knowledge`  
  ↓  
`LLM` (Only receives context that actually matters)

---

## Planned Capabilities

Cognirepo is being built to provide a multi-layered memory system:

### 🧠 Repository Intelligence
* **Documentation Search:** Quickly find relevant internal guides.
* **Context Retrieval:** Fetch specific logic blocks related to a task.
* **Structured Knowledge:** Understanding the project hierarchy and dependencies.

### 💾 Semantic Memory
* Store and retrieve deep knowledge about the codebase.
* Vector-based search for high-relevance context matching.

### ⏳ Episodic Memory
* Record events like previous bug fixes, experiments, or developer feedback.
* Enable agents to "learn" from past interactions within the same repo.

### 🔌 MCP Integration
* Expose tools compatible with the **Model Context Protocol (MCP)**.
* Seamless interaction with popular agent CLIs and IDE extensions.

### ✂️ Memory Pruning
* Automated cleanup to maintain a bounded local memory footprint without losing essential data.

---

## Example Use Case

**Agent Task:** *"How does the chain reaction logic work?"*

**Cognirepo Action:**
1.  Searches **Source Files** for logic patterns.
2.  Queries **Documentation** for architecture overviews.
3.  Retrieves **Previous Memory** (e.g., a note from a fix made two weeks ago).
4.  **Result:** Returns a condensed, highly relevant context package to the LLM.

---

## Project Status

**Status:** `Early Development`

The initial milestone is a minimal MCP-based system focusing on:
* Documentation search
* Semantic & Episodic memory
* Basic repository context retrieval

---

## Contributing

Contributions, ideas, and discussions are welcome! Once the project stabilizes and the core architecture is set, I will be looking for community input and PRs.

---

## Disclaimer

This project is a personal open-source initiative and is not affiliated with any employer.
