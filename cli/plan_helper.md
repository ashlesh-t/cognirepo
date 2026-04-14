##  1. Fix context_pack immediately
  pip install tiktoken
  That one fix probably jumps hit rate to ~55% alone. It's the highest-leverage tool.
  make sure this bundle also gets installed on pip instal cognirepo

## 2. Auto-reindex on file change
  Stale index = fallback to grep. Wire a file watcher or pre-session hook:
  cognirepo index-repo . --changed-only
Internally cognirepo may also uise grep mainly make an graph of traversal from start with function names and nodes are indexed and its bidirectional

##  3. Better embedding coverage
  Current gap: backend/routes/, dynamic code. Fix: chunk at function level not file
  level in AST indexer. Smaller chunks = better similarity scores (0.39-0.51 is too low
  — target >0.65).

## Seed memories after every session
  retrieve_learnings was gold because someone stored learnings. Empty index = useless.
  Make store_memory a post-task habit.

## store users way of talking as an semantic logs so that claude will know what actually user wants ,
This will help invcreasing productivity of bad promt engineers as after a week of usage with lots of debugs , corrections which are all stored as a summarised way also with this logs we can learn users mind

