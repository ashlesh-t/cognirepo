1. smoke-test-index-repo is failing:
Run cognirepo init --password changeme
(trapped) error reading bcrypt version
Traceback (most recent call last):
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 620, in _load_backend_mixin
    version = _bcrypt.__about__.__version__
              ^^^^^^^^^^^^^^^^^
AttributeError: module 'bcrypt' has no attribute '__about__'
Traceback (most recent call last):
  File "/opt/hostedtoolcache/Python/3.11.15/x64/bin/cognirepo", line 6, in <module>
    sys.exit(main())
             ^^^^^^
  File "/home/runner/work/cognirepo/cognirepo/cli/main.py", line 653, in main
    summary, kg, indexer = init_project(
                           ^^^^^^^^^^^^^
  File "/home/runner/work/cognirepo/cognirepo/cli/init_project.py", line 161, in init_project
    _write_config(password, port)
  File "/home/runner/work/cognirepo/cognirepo/cli/init_project.py", line 92, in _write_config
    pw_hash = _hash_password(password)
              ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/cognirepo/cognirepo/cli/init_project.py", line 52, in _hash_password
    return _pwd_ctx.hash(password)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/context.py", line 2258, in hash
    return record.hash(secret, **kwds)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 779, in hash
    self.checksum = self._calc_checksum(secret)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 591, in _calc_checksum
    self._stub_requires_backend()
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2254, in _stub_requires_backend
    cls.set_backend()
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2156, in set_backend
    return owner.set_backend(name, dryrun=dryrun)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2163, in set_backend
    return cls.set_backend(name, dryrun=dryrun)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2188, in set_backend
    cls._set_backend(name, dryrun)
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2311, in _set_backend
    super(SubclassBackendMixin, cls)._set_backend(name, dryrun)
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 2224, in _set_backend
    ok = loader(**kwds)
         ^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 626, in _load_backend_mixin
    return mixin_cls._finalize_backend_mixin(name, dryrun)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 421, in _finalize_backend_mixin
    if detect_wrap_bug(IDENT_2A):
       ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 380, in detect_wrap_bug
    if verify(secret, bug_hash):
       ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/utils/handlers.py", line 792, in verify
    return consteq(self._calc_checksum(secret), chk)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/passlib/handlers/bcrypt.py", line 655, in _calc_checksum
    hash = _bcrypt.hashpw(secret, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary (e.g. my_password[:72])





2. git guardian issues:
🔎 Detected hardcoded secrets in your pull request
Pull request #5: development 👉 main
GitGuardian id	GitGuardian status	Secret	Commit	Filename	
29292140	Triggered	Generic Password	f3b8f777c8c97a5810cf5de9bc3a0403b45fcd31	api/auth.py	View secret




3. lint issues
1s
1s
0s
1m 49s
1m 28s
Run pylint $(git ls-files '*.py')
************* Module _bm25._fallback
_bm25/_fallback.py:73:4: R0914: Too many local variables (16/15) (too-many-locals)
_bm25/_fallback.py:22:0: W0611: Unused field imported from dataclasses (unused-import)
************* Module adapters.__init__
adapters/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module api.__init__
api/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module api.auth
api/auth.py:31:0: C0115: Missing class docstring (missing-class-docstring)
************* Module api.main
api/main.py:26:0: C0301: Line too long (116/100) (line-too-long)
************* Module api.middleware
api/middleware.py:22:0: C0115: Missing class docstring (missing-class-docstring)
api/middleware.py:22:0: R0903: Too few public methods (1/2) (too-few-public-methods)
************* Module api.routes.__init__
api/routes/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module api.routes.episodic
api/routes/episodic.py:24:0: C0115: Missing class docstring (missing-class-docstring)
************* Module api.routes.graph
api/routes/graph.py:26:0: C0103: Constant name "_graph" doesn't conform to UPPER_CASE naming style (invalid-name)
api/routes/graph.py:27:0: C0103: Constant name "_indexer" doesn't conform to UPPER_CASE naming style (invalid-name)
api/routes/graph.py:31:4: W0603: Using the global statement (global-statement)
api/routes/graph.py:33:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
api/routes/graph.py:39:4: W0603: Using the global statement (global-statement)
api/routes/graph.py:41:8: C0415: Import outside toplevel (indexer.ast_indexer.ASTIndexer) (import-outside-toplevel)
api/routes/graph.py:125:12: W0108: Lambda may not be necessary (unnecessary-lambda)
************* Module api.routes.memory
api/routes/memory.py:24:0: C0115: Missing class docstring (missing-class-docstring)
api/routes/memory.py:29:0: C0115: Missing class docstring (missing-class-docstring)
************* Module cli.__init__
cli/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module cli.api_client
cli/api_client.py:46:0: C0301: Line too long (111/100) (line-too-long)
cli/api_client.py:79:4: C0116: Missing function or method docstring (missing-function-docstring)
cli/api_client.py:84:4: C0116: Missing function or method docstring (missing-function-docstring)
cli/api_client.py:88:4: C0116: Missing function or method docstring (missing-function-docstring)
cli/api_client.py:92:4: C0116: Missing function or method docstring (missing-function-docstring)
cli/api_client.py:96:4: C0116: Missing function or method docstring (missing-function-docstring)
cli/api_client.py:100:4: C0116: Missing function or method docstring (missing-function-docstring)
************* Module cli.init_project
cli/init_project.py:53:11: E0601: Using variable '_bcrypt' before assignment (used-before-assignment)
************* Module cli.main
cli/main.py:337:0: C0301: Line too long (103/100) (line-too-long)
cli/main.py:487:0: C0301: Line too long (107/100) (line-too-long)
cli/main.py:534:0: C0301: Line too long (104/100) (line-too-long)
cli/main.py:47:4: C0415: Import outside toplevel (tools.store_memory.store_memory) (import-outside-toplevel)
cli/main.py:52:4: C0415: Import outside toplevel (tools.retrieve_memory.retrieve_memory) (import-outside-toplevel)
cli/main.py:57:4: C0415: Import outside toplevel (retrieval.docs_search.search_docs) (import-outside-toplevel)
cli/main.py:61:0: R0914: Too many local variables (52/15) (too-many-locals)
cli/main.py:90:8: W0404: Reimport 'json' (imported line 21) (reimported)
cli/main.py:166:8: C0103: Variable name "_EXT_NAMES" doesn't conform to snake_case naming style (invalid-name)
cli/main.py:184:4: C0103: Variable name "_PROVIDERS" doesn't conform to snake_case naming style (invalid-name)
cli/main.py:207:20: E1101: Instance of 'CircuitBreaker' has no '_rss_limit_mb' member (no-member)
cli/main.py:61:0: R0912: Too many branches (27/12) (too-many-branches)
cli/main.py:61:0: R0915: Too many statements (135/50) (too-many-statements)
cli/main.py:259:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
cli/main.py:267:4: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
cli/main.py:273:4: C0415: Import outside toplevel (memory.episodic_memory.get_history) (import-outside-toplevel)
cli/main.py:278:4: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
cli/main.py:279:4: C0415: Import outside toplevel (indexer.ast_indexer.ASTIndexer) (import-outside-toplevel)
cli/main.py:289:4: C0415: Import outside toplevel (os) (import-outside-toplevel)
cli/main.py:290:4: C0415: Import outside toplevel (graph.behaviour_tracker.BehaviourTracker) (import-outside-toplevel)
cli/main.py:291:4: C0415: Import outside toplevel (indexer.file_watcher.create_watcher) (import-outside-toplevel)
cli/main.py:382:0: R0913: Too many arguments (8/5) (too-many-arguments)
cli/main.py:382:0: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
cli/main.py:382:0: R0914: Too many local variables (20/15) (too-many-locals)
cli/main.py:416:12: W0404: Reimport 'json' (imported line 21) (reimported)
cli/main.py:470:0: C0116: Missing function or method docstring (missing-function-docstring)
cli/main.py:470:0: R0914: Too many local variables (43/15) (too-many-locals)
cli/main.py:712:8: C0103: Variable name "_KEY_ENV" doesn't conform to snake_case naming style (invalid-name)
cli/main.py:764:8: C0415: Import outside toplevel (cli.api_client.ApiClient) (import-outside-toplevel)
cli/main.py:470:0: R0911: Too many return statements (11/6) (too-many-return-statements)
cli/main.py:470:0: R0912: Too many branches (40/12) (too-many-branches)
cli/main.py:470:0: R0915: Too many statements (168/50) (too-many-statements)
************* Module cli.repl
cli/repl.py:43:4: C0415: Import outside toplevel (json) (import-outside-toplevel)
cli/repl.py:44:4: C0415: Import outside toplevel (os) (import-outside-toplevel)
cli/repl.py:107:0: R0914: Too many local variables (17/15) (too-many-locals)
cli/repl.py:117:8: C0415: Import outside toplevel (readline) (import-outside-toplevel)
cli/repl.py:173:22: W1309: Using an f-string that does not have any interpolated variables (f-string-without-interpolation)
cli/repl.py:107:0: R0912: Too many branches (15/12) (too-many-branches)
cli/repl.py:107:0: R0915: Too many statements (61/50) (too-many-statements)
************* Module cli.seed
cli/seed.py:31:0: R0914: Too many local variables (26/15) (too-many-locals)
cli/seed.py:62:15: W1510: 'subprocess.run' used without explicitly defining the value for 'check'. (subprocess-run-check)
cli/seed.py:31:0: R0912: Too many branches (23/12) (too-many-branches)
cli/seed.py:31:0: R0915: Too many statements (57/50) (too-many-statements)
************* Module prune_memory
cron/prune_memory.py:199:0: C0301: Line too long (102/100) (line-too-long)
cron/prune_memory.py:57:8: W0611: Unused CircuitOpenError imported from memory.circuit_breaker (unused-import)
cron/prune_memory.py:111:8: E1120: No value for argument 'x' in method call (no-value-for-parameter)
cron/prune_memory.py:103:8: W0611: Unused numpy imported as np (unused-import)
cron/prune_memory.py:166:0: R0914: Too many local variables (19/15) (too-many-locals)
cron/prune_memory.py:232:0: C0116: Missing function or method docstring (missing-function-docstring)
cron/prune_memory.py:37:0: W0611: Unused import shutil (unused-import)
************* Module graph.__init__
graph/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module graph.behaviour_tracker
graph/behaviour_tracker.py:165:0: C0301: Line too long (102/100) (line-too-long)
graph/behaviour_tracker.py:64:4: C0116: Missing function or method docstring (missing-function-docstring)
graph/behaviour_tracker.py:167:4: C0116: Missing function or method docstring (missing-function-docstring)
graph/behaviour_tracker.py:195:8: C0415: Import outside toplevel (indexer.file_watcher.create_watcher) (import-outside-toplevel)
graph/behaviour_tracker.py:199:4: C0116: Missing function or method docstring (missing-function-docstring)
************* Module graph.graph_utils
graph/graph_utils.py:66:0: R0911: Too many return statements (8/6) (too-many-return-statements)
************* Module graph.knowledge_graph
graph/knowledge_graph.py:200:0: C0301: Line too long (104/100) (line-too-long)
graph/knowledge_graph.py:29:0: C0115: Missing class docstring (missing-class-docstring)
graph/knowledge_graph.py:29:0: R0903: Too few public methods (0/2) (too-few-public-methods)
graph/knowledge_graph.py:39:0: C0115: Missing class docstring (missing-class-docstring)
graph/knowledge_graph.py:39:0: R0903: Too few public methods (0/2) (too-few-public-methods)
graph/knowledge_graph.py:51:8: C0103: Attribute name "G" doesn't conform to snake_case naming style (invalid-name)
graph/knowledge_graph.py:76:4: C0116: Missing function or method docstring (missing-function-docstring)
graph/knowledge_graph.py:124:4: C0116: Missing function or method docstring (missing-function-docstring)
graph/knowledge_graph.py:206:4: C0116: Missing function or method docstring (missing-function-docstring)
************* Module indexer.__init__
indexer/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module indexer.ast_indexer
indexer/ast_indexer.py:192:39: W0613: Unused argument 'file_path' (unused-argument)
indexer/ast_indexer.py:306:4: R0914: Too many local variables (16/15) (too-many-locals)
indexer/ast_indexer.py:374:4: R0914: Too many local variables (18/15) (too-many-locals)
indexer/ast_indexer.py:478:4: C0116: Missing function or method docstring (missing-function-docstring)
indexer/ast_indexer.py:42:0: W0611: Unused SymbolRecord imported from indexer.index_utils (unused-import)
indexer/ast_indexer.py:43:0: W0611: Unused supported_extensions imported from indexer.language_registry (unused-import)
************* Module indexer.file_watcher
indexer/file_watcher.py:40:4: R0913: Too many arguments (6/5) (too-many-arguments)
indexer/file_watcher.py:40:4: R0917: Too many positional arguments (6/5) (too-many-positional-arguments)
indexer/file_watcher.py:55:4: C0116: Missing function or method docstring (missing-function-docstring)
indexer/file_watcher.py:59:4: C0116: Missing function or method docstring (missing-function-docstring)
indexer/file_watcher.py:63:4: C0116: Missing function or method docstring (missing-function-docstring)
indexer/file_watcher.py:82:12: W0212: Access to a protected member _build_reverse_index of a client class (protected-access)
indexer/file_watcher.py:109:12: W0212: Access to a protected member _build_reverse_index of a client class (protected-access)
************* Module indexer.index_utils
indexer/index_utils.py:25:0: C0115: Missing class docstring (missing-class-docstring)
indexer/index_utils.py:69:4: C0116: Missing function or method docstring (missing-function-docstring)
************* Module indexer.language_registry
indexer/language_registry.py:79:0: C0103: Constant name "_ts_available" doesn't conform to UPPER_CASE naming style (invalid-name)
************* Module memory.__init__
memory/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module memory.circuit_breaker
memory/circuit_breaker.py:55:0: C0115: Missing class docstring (missing-class-docstring)
memory/circuit_breaker.py:141:4: C0116: Missing function or method docstring (missing-function-docstring)
memory/circuit_breaker.py:181:4: C0116: Missing function or method docstring (missing-function-docstring)
memory/circuit_breaker.py:187:4: C0116: Missing function or method docstring (missing-function-docstring)
memory/circuit_breaker.py:232:0: C0103: Constant name "_breaker" doesn't conform to UPPER_CASE naming style (invalid-name)
************* Module orchestrator.__init__
orchestrator/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module orchestrator.classifier
orchestrator/classifier.py:224:0: C0325: Unnecessary parens after 'not' keyword (superfluous-parens)
orchestrator/classifier.py:71:0: C0115: Missing class docstring (missing-class-docstring)
************* Module orchestrator.context_builder
orchestrator/context_builder.py:55:0: C0103: Constant name "_shared_retriever" doesn't conform to UPPER_CASE naming style (invalid-name)
orchestrator/context_builder.py:71:0: C0115: Missing class docstring (missing-class-docstring)
orchestrator/context_builder.py:71:0: R0902: Too many instance attributes (10/7) (too-many-instance-attributes)
orchestrator/context_builder.py:115:0: R0914: Too many local variables (27/15) (too-many-locals)
orchestrator/context_builder.py:275:12: C0415: Import outside toplevel (server.mcp_server._write_manifest) (import-outside-toplevel)
************* Module orchestrator.model_adapters.__init__
orchestrator/model_adapters/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module orchestrator.model_adapters.anthropic_adapter
orchestrator/model_adapters/anthropic_adapter.py:33:0: C0115: Missing class docstring (missing-class-docstring)
orchestrator/model_adapters/anthropic_adapter.py:42:0: R0913: Too many arguments (8/5) (too-many-arguments)
orchestrator/model_adapters/anthropic_adapter.py:42:0: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
orchestrator/model_adapters/anthropic_adapter.py:42:0: R0914: Too many local variables (21/15) (too-many-locals)
orchestrator/model_adapters/anthropic_adapter.py:151:12: R1737: Use 'yield from' directly instead of yielding each element one by one (use-yield-from)
orchestrator/model_adapters/anthropic_adapter.py:141:4: W0613: Unused argument 'model_id' (unused-argument)
************* Module orchestrator.model_adapters.gemini_adapter
orchestrator/model_adapters/gemini_adapter.py:33:0: R0913: Too many arguments (8/5) (too-many-arguments)
orchestrator/model_adapters/gemini_adapter.py:33:0: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
orchestrator/model_adapters/gemini_adapter.py:33:0: R0914: Too many local variables (26/15) (too-many-locals)
orchestrator/model_adapters/gemini_adapter.py:163:0: R0912: Too many branches (17/12) (too-many-branches)
************* Module orchestrator.model_adapters.grok_adapter
orchestrator/model_adapters/grok_adapter.py:28:0: R0913: Too many arguments (8/5) (too-many-arguments)
orchestrator/model_adapters/grok_adapter.py:28:0: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
orchestrator/model_adapters/grok_adapter.py:21:0: W0611: Unused ModelResponse imported from orchestrator.model_adapters.anthropic_adapter (unused-import)
************* Module orchestrator.model_adapters.openai_adapter
orchestrator/model_adapters/openai_adapter.py:76:0: C0301: Line too long (102/100) (line-too-long)
orchestrator/model_adapters/openai_adapter.py:39:0: R0913: Too many arguments (11/5) (too-many-arguments)
orchestrator/model_adapters/openai_adapter.py:39:0: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
orchestrator/model_adapters/openai_adapter.py:39:0: R0914: Too many local variables (30/15) (too-many-locals)
orchestrator/model_adapters/openai_adapter.py:158:4: C0103: Argument name "RateLimitError" doesn't conform to snake_case naming style (invalid-name)
orchestrator/model_adapters/openai_adapter.py:159:4: C0103: Argument name "AuthenticationError" doesn't conform to snake_case naming style (invalid-name)
orchestrator/model_adapters/openai_adapter.py:160:4: C0103: Argument name "APIStatusError" doesn't conform to snake_case naming style (invalid-name)
orchestrator/model_adapters/openai_adapter.py:161:4: C0103: Argument name "APIConnectionError" doesn't conform to snake_case naming style (invalid-name)
orchestrator/model_adapters/openai_adapter.py:154:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/model_adapters/openai_adapter.py:154:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
************* Module orchestrator.router
orchestrator/router.py:370:0: C0301: Line too long (123/100) (line-too-long)
orchestrator/router.py:50:0: C0413: Import "from orchestrator.classifier import ClassifierResult, classify" should be placed at the top of the module (wrong-import-position)
orchestrator/router.py:51:0: C0413: Import "from orchestrator.context_builder import ContextBundle, build as build_context" should be placed at the top of the module (wrong-import-position)
orchestrator/router.py:52:0: C0413: Import "from orchestrator.model_adapters.anthropic_adapter import ModelResponse" should be placed at the top of the module (wrong-import-position)
orchestrator/router.py:53:0: C0413: Import "from orchestrator.model_adapters.errors import ModelCallError" should be placed at the top of the module (wrong-import-position)
orchestrator/router.py:60:0: C0103: Constant name "_grpc_warned" doesn't conform to UPPER_CASE naming style (invalid-name)
orchestrator/router.py:61:0: C0103: Constant name "_grpc_process" doesn't conform to UPPER_CASE naming style (invalid-name)
orchestrator/router.py:62:0: C0103: Constant name "_grpc_autostart_done" doesn't conform to UPPER_CASE naming style (invalid-name)
orchestrator/router.py:137:0: C0115: Missing class docstring (missing-class-docstring)
orchestrator/router.py:151:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/router.py:151:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
orchestrator/router.py:151:0: R0914: Too many local variables (18/15) (too-many-locals)
orchestrator/router.py:249:33: W0613: Unused argument 'bundle' (unused-argument)
orchestrator/router.py:340:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/router.py:340:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
orchestrator/router.py:340:0: R0914: Too many local variables (16/15) (too-many-locals)
orchestrator/router.py:389:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/router.py:389:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
orchestrator/router.py:399:13: R1735: Consider using '{"query": query, "system_prompt": system_prompt, "tool_manifest": tool_manifest, ... }' instead of a call to 'dict'. (use-dict-literal)
orchestrator/router.py:468:8: W0621: Redefining name 'os' from outer scope (line 41) (redefined-outer-name)
orchestrator/router.py:468:8: W0404: Reimport 'os' (imported line 41) (reimported)
orchestrator/router.py:502:8: W0621: Redefining name 'os' from outer scope (line 41) (redefined-outer-name)
orchestrator/router.py:502:8: W0404: Reimport 'os' (imported line 41) (reimported)
orchestrator/router.py:509:8: C0103: Variable name "G" doesn't conform to snake_case naming style (invalid-name)
orchestrator/router.py:537:8: W0621: Redefining name 'json' from outer scope (line 39) (redefined-outer-name)
orchestrator/router.py:538:8: W0621: Redefining name 'os' from outer scope (line 41) (redefined-outer-name)
orchestrator/router.py:537:8: W0404: Reimport 'json' (imported line 39) (reimported)
orchestrator/router.py:538:8: W0404: Reimport 'os' (imported line 41) (reimported)
orchestrator/router.py:561:8: C0103: Variable name "G" doesn't conform to snake_case naming style (invalid-name)
orchestrator/router.py:586:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/router.py:586:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
orchestrator/router.py:586:0: R0914: Too many local variables (17/15) (too-many-locals)
orchestrator/router.py:664:0: R0913: Too many arguments (7/5) (too-many-arguments)
orchestrator/router.py:664:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
orchestrator/router.py:674:13: R1735: Consider using '{"query": query, "system_prompt": system_prompt, "tool_manifest": tool_manifest, ... }' instead of a call to 'dict'. (use-dict-literal)
************* Module retrieval.__init__
retrieval/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module retrieval.hybrid
retrieval/hybrid.py:59:0: R0903: Too few public methods (1/2) (too-few-public-methods)
************* Module rpc.__init__
rpc/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module rpc.client
rpc/client.py:63:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/client.py:69:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/client.py:82:4: R0913: Too many arguments (8/5) (too-many-arguments)
rpc/client.py:82:4: R0917: Too many positional arguments (8/5) (too-many-positional-arguments)
rpc/client.py:106:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/client.py:116:4: R0913: Too many arguments (7/5) (too-many-arguments)
rpc/client.py:116:4: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
rpc/client.py:127:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/client.py:138:4: R0913: Too many arguments (6/5) (too-many-arguments)
rpc/client.py:138:4: R0917: Too many positional arguments (6/5) (too-many-positional-arguments)
rpc/client.py:149:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncRequest' member (no-member)
rpc/client.py:166:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetRequest' member (no-member)
rpc/client.py:173:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsRequest' member (no-member)
rpc/client.py:186:0: R0913: Too many arguments (7/5) (too-many-arguments)
rpc/client.py:186:0: R0917: Too many positional arguments (7/5) (too-many-positional-arguments)
************* Module rpc.context_store
rpc/context_store.py:33:0: C0115: Missing class docstring (missing-class-docstring)
rpc/context_store.py:69:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/context_store.py:119:0: C0103: Constant name "_store" doesn't conform to UPPER_CASE naming style (invalid-name)
rpc/context_store.py:122:0: C0116: Missing function or method docstring (missing-function-docstring)
************* Module rpc.proto.__init__
rpc/proto/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module rpc.proto.cognirepo_pb2
rpc/proto/cognirepo_pb2.py:28:0: C0301: Line too long (2256/100) (line-too-long)
rpc/proto/cognirepo_pb2.py:34:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:35:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:36:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:37:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:38:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:39:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:40:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:41:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:42:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:43:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:44:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:45:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:46:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:47:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:48:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:49:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:50:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:51:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:52:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:53:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:54:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:55:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:56:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:57:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:58:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:59:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:60:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:61:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:62:0: W0311: Bad indentation. Found 2 spaces, expected 4 (bad-indentation)
rpc/proto/cognirepo_pb2.py:8:0: E0611: No name 'protobuf' in module 'google' (no-name-in-module)
rpc/proto/cognirepo_pb2.py:9:0: E0611: No name 'protobuf' in module 'google' (no-name-in-module)
rpc/proto/cognirepo_pb2.py:10:0: E0611: No name 'protobuf' in module 'google' (no-name-in-module)
rpc/proto/cognirepo_pb2.py:11:0: E0611: No name 'protobuf' in module 'google' (no-name-in-module)
rpc/proto/cognirepo_pb2.py:12:0: E0611: No name 'protobuf' in module 'google' (no-name-in-module)
rpc/proto/cognirepo_pb2.py:33:7: W0212: Access to a protected member _USE_C_DESCRIPTORS of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:34:2: W0212: Access to a protected member _loaded_options of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:35:2: W0212: Access to a protected member _loaded_options of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:36:2: W0212: Access to a protected member _serialized_options of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:37:2: W0212: Access to a protected member _loaded_options of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:38:2: W0212: Access to a protected member _serialized_options of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:39:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:40:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:41:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:42:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:43:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:44:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:45:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:46:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:47:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:48:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:49:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:50:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:51:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:52:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:53:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:54:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:55:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:56:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:57:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:58:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:59:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:60:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:61:2: W0212: Access to a protected member _serialized_start of a client class (protected-access)
rpc/proto/cognirepo_pb2.py:62:2: W0212: Access to a protected member _serialized_end of a client class (protected-access)
************* Module rpc.proto.cognirepo_pb2_grpc
rpc/proto/cognirepo_pb2_grpc.py:42:8: C0103: Attribute name "SubQuery" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:47:8: C0103: Attribute name "SubQueryStream" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:29:0: R0205: Class 'QueryServiceStub' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:44:35: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:45:38: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:49:35: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:50:38: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:29:0: R0903: Too few public methods (0/2) (too-few-public-methods)
rpc/proto/cognirepo_pb2_grpc.py:54:0: R0205: Class 'QueryServiceServicer' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:61:4: C0103: Method name "SubQuery" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:61:23: W0613: Unused argument 'request' (unused-argument)
rpc/proto/cognirepo_pb2_grpc.py:68:4: C0103: Method name "SubQueryStream" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:68:29: W0613: Unused argument 'request' (unused-argument)
rpc/proto/cognirepo_pb2_grpc.py:76:0: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:76:0: C0103: Function name "add_QueryServiceServicer_to_server" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:80:41: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:81:40: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:85:41: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:86:40: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:96:0: R0205: Class 'QueryService' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:104:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:104:4: C0103: Method name "SubQuery" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:104:4: R0913: Too many arguments (10/5) (too-many-arguments)
rpc/proto/cognirepo_pb2_grpc.py:104:4: R0917: Too many positional arguments (10/5) (too-many-positional-arguments)
rpc/proto/cognirepo_pb2_grpc.py:118:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:119:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:131:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:131:4: C0103: Method name "SubQueryStream" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:131:4: R0913: Too many arguments (10/5) (too-many-arguments)
rpc/proto/cognirepo_pb2_grpc.py:131:4: R0917: Too many positional arguments (10/5) (too-many-positional-arguments)
rpc/proto/cognirepo_pb2_grpc.py:145:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:146:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:170:8: C0103: Attribute name "PushContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:175:8: C0103: Attribute name "GetContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:180:8: C0103: Attribute name "ListSessions" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:158:0: R0205: Class 'ContextServiceStub' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:172:35: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:173:38: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:177:35: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:178:38: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:182:35: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:183:38: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:158:0: R0903: Too few public methods (0/2) (too-few-public-methods)
rpc/proto/cognirepo_pb2_grpc.py:187:0: R0205: Class 'ContextServiceServicer' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:193:4: C0103: Method name "PushContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:193:26: W0613: Unused argument 'request' (unused-argument)
rpc/proto/cognirepo_pb2_grpc.py:200:4: C0103: Method name "GetContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:200:25: W0613: Unused argument 'request' (unused-argument)
rpc/proto/cognirepo_pb2_grpc.py:207:4: C0103: Method name "ListSessions" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:207:27: W0613: Unused argument 'request' (unused-argument)
rpc/proto/cognirepo_pb2_grpc.py:215:0: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:215:0: C0103: Function name "add_ContextServiceServicer_to_server" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:219:41: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:220:40: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:224:41: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:225:40: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:229:41: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:230:40: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:240:0: R0205: Class 'ContextService' inherits from object, can be safely removed from bases in python3 (useless-object-inheritance)
rpc/proto/cognirepo_pb2_grpc.py:247:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:247:4: C0103: Method name "PushContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:247:4: R0913: Too many arguments (10/5) (too-many-arguments)
rpc/proto/cognirepo_pb2_grpc.py:247:4: R0917: Too many positional arguments (10/5) (too-many-positional-arguments)
rpc/proto/cognirepo_pb2_grpc.py:261:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:262:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:274:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:274:4: C0103: Method name "GetContext" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:274:4: R0913: Too many arguments (10/5) (too-many-arguments)
rpc/proto/cognirepo_pb2_grpc.py:274:4: R0917: Too many positional arguments (10/5) (too-many-positional-arguments)
rpc/proto/cognirepo_pb2_grpc.py:288:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:289:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:301:4: C0116: Missing function or method docstring (missing-function-docstring)
rpc/proto/cognirepo_pb2_grpc.py:301:4: C0103: Method name "ListSessions" doesn't conform to snake_case naming style (invalid-name)
rpc/proto/cognirepo_pb2_grpc.py:301:4: R0913: Too many arguments (10/5) (too-many-arguments)
rpc/proto/cognirepo_pb2_grpc.py:301:4: R0917: Too many positional arguments (10/5) (too-many-positional-arguments)
rpc/proto/cognirepo_pb2_grpc.py:315:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsRequest' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:316:12: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsResponse' member (no-member)
rpc/proto/cognirepo_pb2_grpc.py:5:0: C0411: standard import "warnings" should be placed before third party import "grpc" (wrong-import-order)
rpc/proto/cognirepo_pb2_grpc.py:5:0: W0611: Unused import warnings (unused-import)
************* Module rpc.server
rpc/server.py:47:0: C0301: Line too long (102/100) (line-too-long)
rpc/server.py:63:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/server.py:73:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/server.py:97:18: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'QueryResponse' member (no-member)
rpc/server.py:121:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncResponse' member (no-member)
rpc/server.py:125:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextSyncResponse' member (no-member)
rpc/server.py:136:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetResponse' member (no-member)
rpc/server.py:144:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ContextGetResponse' member (no-member)
rpc/server.py:154:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsResponse' member (no-member)
rpc/server.py:158:19: E1101: Module 'rpc.proto.cognirepo_pb2' has no 'ListSessionsResponse' member (no-member)
rpc/server.py:198:0: C0116: Missing function or method docstring (missing-function-docstring)
rpc/server.py:28:0: W0611: Unused import sys (unused-import)
************* Module server.__init__
server/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module server.mcp_server
server/mcp_server.py:190:0: C0301: Line too long (114/100) (line-too-long)
server/mcp_server.py:202:0: C0301: Line too long (103/100) (line-too-long)
server/mcp_server.py:209:0: C0301: Line too long (101/100) (line-too-long)
server/mcp_server.py:213:0: C0301: Line too long (102/100) (line-too-long)
server/mcp_server.py:225:0: C0301: Line too long (117/100) (line-too-long)
server/mcp_server.py:232:0: C0301: Line too long (118/100) (line-too-long)
server/mcp_server.py:247:0: C0301: Line too long (122/100) (line-too-long)
server/mcp_server.py:254:0: C0301: Line too long (106/100) (line-too-long)
server/mcp_server.py:258:0: C0301: Line too long (120/100) (line-too-long)
server/mcp_server.py:270:0: C0301: Line too long (105/100) (line-too-long)
server/mcp_server.py:271:0: C0301: Line too long (112/100) (line-too-long)
server/mcp_server.py:23:0: C0103: Constant name "_graph" doesn't conform to UPPER_CASE naming style (invalid-name)
server/mcp_server.py:24:0: C0103: Constant name "_indexer" doesn't conform to UPPER_CASE naming style (invalid-name)
server/mcp_server.py:28:4: W0603: Using the global statement (global-statement)
server/mcp_server.py:30:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
server/mcp_server.py:36:4: W0603: Using the global statement (global-statement)
server/mcp_server.py:38:8: C0415: Import outside toplevel (indexer.ast_indexer.ASTIndexer) (import-outside-toplevel)
server/mcp_server.py:105:4: C0415: Import outside toplevel (graph.knowledge_graph.EdgeType) (import-outside-toplevel)
server/mcp_server.py:160:12: W0108: Lambda may not be necessary (unnecessary-lambda)
************* Module tests.__init__
tests/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module tests.conftest
tests/conftest.py:70:9: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/conftest.py:20:0: W0611: Unused import tempfile (unused-import)
************* Module tests.test_adapters
tests/test_adapters.py:454:0: C0301: Line too long (102/100) (line-too-long)
tests/test_adapters.py:58:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:59:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:60:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:65:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:66:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:71:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:72:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:76:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:77:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:85:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:86:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:87:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:92:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:93:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:94:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:109:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:110:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:111:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:125:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:126:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:127:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:141:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:142:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:143:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:156:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:157:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:158:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:172:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:173:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:174:8: C0415: Import outside toplevel (orchestrator.model_adapters.retry.with_retry) (import-outside-toplevel)
tests/test_adapters.py:177:42: W0108: Lambda may not be necessary (unnecessary-lambda)
tests/test_adapters.py:190:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:191:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:197:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:203:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:209:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:215:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:217:8: C0415: Import outside toplevel (anthropic) (import-outside-toplevel)
tests/test_adapters.py:225:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:226:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:232:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:234:8: C0415: Import outside toplevel (anthropic) (import-outside-toplevel)
tests/test_adapters.py:242:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:243:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:251:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:252:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:258:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:264:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:266:8: C0415: Import outside toplevel (openai) (import-outside-toplevel)
tests/test_adapters.py:274:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:275:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:280:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:282:8: C0415: Import outside toplevel (openai) (import-outside-toplevel)
tests/test_adapters.py:287:0: W0613: Unused argument 'args' (unused-argument)
tests/test_adapters.py:287:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:296:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:297:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:305:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:306:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:319:12: C0415: Import outside toplevel (orchestrator.model_adapters.grok_adapter) (import-outside-toplevel)
tests/test_adapters.py:326:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:334:12: C0415: Import outside toplevel (orchestrator.model_adapters.grok_adapter) (import-outside-toplevel)
tests/test_adapters.py:343:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:344:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:358:12: C0415: Import outside toplevel (importlib) (import-outside-toplevel)
tests/test_adapters.py:359:12: C0415: Import outside toplevel (orchestrator.model_adapters.gemini_adapter) (import-outside-toplevel)
tests/test_adapters.py:364:19: W0718: Catching too general exception Exception (broad-exception-caught)
tests/test_adapters.py:371:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:373:8: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:376:8: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:376:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_adapters.py:381:8: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:381:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_adapters.py:390:8: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:390:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_adapters.py:401:12: C0415: Import outside toplevel (importlib) (import-outside-toplevel)
tests/test_adapters.py:402:12: C0415: Import outside toplevel (orchestrator.model_adapters.gemini_adapter) (import-outside-toplevel)
tests/test_adapters.py:407:19: W0718: Catching too general exception Exception (broad-exception-caught)
tests/test_adapters.py:413:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:414:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:420:8: C0415: Import outside toplevel (orchestrator.router._available_providers) (import-outside-toplevel)
tests/test_adapters.py:425:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:430:8: C0415: Import outside toplevel (orchestrator.router._available_providers) (import-outside-toplevel)
tests/test_adapters.py:431:15: C1803: "_available_providers(...) == []" can be simplified to "not _available_providers(...)", if it is strictly a sequence, as an empty list is falsey (use-implicit-booleaness-not-comparison)
tests/test_adapters.py:441:8: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:442:8: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter.ModelResponse) (import-outside-toplevel)
tests/test_adapters.py:446:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:450:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:456:12: C0415: Import outside toplevel (orchestrator.router) (import-outside-toplevel)
tests/test_adapters.py:457:21: W0212: Access to a protected member _dispatch_with_fallback of a client class (protected-access)
tests/test_adapters.py:477:19: E0601: Using variable 'usage' before assignment (used-before-assignment)
tests/test_adapters.py:496:8: W0612: Unused variable 'i' (unused-variable)
tests/test_adapters.py:509:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:510:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:517:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:522:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:529:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:534:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:541:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:544:15: E1101: Class 'value' has no 'get' member (no-member)
tests/test_adapters.py:545:15: E1101: Class 'value' has no 'get' member (no-member)
tests/test_adapters.py:547:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:552:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:554:8: C0415: Import outside toplevel (inspect) (import-outside-toplevel)
tests/test_adapters.py:557:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:559:8: C0415: Import outside toplevel (anthropic) (import-outside-toplevel)
tests/test_adapters.py:565:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:566:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:578:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_adapters.py:579:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter.ModelResponse) (import-outside-toplevel)
tests/test_adapters.py:587:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:588:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:595:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:600:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:607:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:612:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:619:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:622:15: E1101: Class 'value' has no 'get' member (no-member)
tests/test_adapters.py:623:15: E1101: Class 'value' has no 'get' member (no-member)
tests/test_adapters.py:625:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:630:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:632:8: C0415: Import outside toplevel (inspect) (import-outside-toplevel)
tests/test_adapters.py:635:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:637:8: C0415: Import outside toplevel (openai) (import-outside-toplevel)
tests/test_adapters.py:643:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:644:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:663:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_adapters.py:671:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:672:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:687:12: C0415: Import outside toplevel (orchestrator.model_adapters.grok_adapter) (import-outside-toplevel)
tests/test_adapters.py:698:8: C0415: Import outside toplevel (openai) (import-outside-toplevel)
tests/test_adapters.py:705:12: C0415: Import outside toplevel (orchestrator.model_adapters.grok_adapter) (import-outside-toplevel)
tests/test_adapters.py:706:12: C0415: Import outside toplevel (orchestrator.model_adapters.errors.ModelCallError) (import-outside-toplevel)
tests/test_adapters.py:715:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_adapters.py:718:8: C0415: Import outside toplevel (orchestrator.classifier.ClassifierResult) (import-outside-toplevel)
tests/test_adapters.py:719:8: C0415: Import outside toplevel (orchestrator.context_builder.ContextBundle) (import-outside-toplevel)
tests/test_adapters.py:731:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:734:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:741:12: C0415: Import outside toplevel (orchestrator.router.stream_route) (import-outside-toplevel)
tests/test_adapters.py:757:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:763:12: C0415: Import outside toplevel (orchestrator.router.stream_route) (import-outside-toplevel)
tests/test_adapters.py:769:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_adapters.py:772:0: W0613: Unused argument 'kwargs' (unused-argument)
tests/test_adapters.py:778:12: C0415: Import outside toplevel (orchestrator.router.stream_route) (import-outside-toplevel)
tests/test_adapters.py:779:12: C0415: Import outside toplevel (inspect) (import-outside-toplevel)
tests/test_adapters.py:15:0: W0611: Unused import json (unused-import)
tests/test_adapters.py:16:0: W0611: Unused call imported from unittest.mock as mock_call (unused-import)
************* Module tests.test_api
tests/test_api.py:125:0: C0301: Line too long (101/100) (line-too-long)
tests/test_api.py:21:4: C0415: Import outside toplevel (fastapi.testclient.TestClient) (import-outside-toplevel)
tests/test_api.py:22:4: C0415: Import outside toplevel (api.main.app) (import-outside-toplevel)
tests/test_api.py:27:17: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:37:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_api.py:38:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:38:49: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:42:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:42:58: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:46:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:46:39: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:54:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_api.py:55:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:55:32: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:55:40: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:65:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:65:35: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:65:43: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:80:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:80:41: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:80:49: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:90:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_api.py:91:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:91:31: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:91:39: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:99:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:99:31: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:99:39: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:109:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:109:47: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:109:55: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:119:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:119:51: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:119:59: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:130:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:130:49: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:135:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_api.py:136:45: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:136:53: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:143:45: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:143:53: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:156:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:156:47: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:160:39: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:160:47: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:167:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:167:41: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:171:40: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:171:48: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:179:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:179:40: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:179:48: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:183:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:183:49: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:183:57: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:188:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:188:42: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:192:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:192:43: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:192:51: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:200:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:200:51: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:200:59: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:207:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:207:45: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:211:66: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:211:74: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:221:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:221:60: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:221:68: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
tests/test_api.py:228:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_api.py:228:61: W0621: Redefining name 'client' from outer scope (line 19) (redefined-outer-name)
tests/test_api.py:228:69: W0621: Redefining name 'auth_headers' from outer scope (line 27) (redefined-outer-name)
************* Module tests.test_bm25
tests/test_bm25.py:30:4: C0415: Import outside toplevel (_bm25.BM25) (import-outside-toplevel)
tests/test_bm25.py:35:4: C0415: Import outside toplevel (_bm25.Document) (import-outside-toplevel)
tests/test_bm25.py:41:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_bm25.py:42:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:43:8: C0415: Import outside toplevel (_bm25.BACKEND) (import-outside-toplevel)
tests/test_bm25.py:46:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:47:8: C0415: Import outside toplevel (_bm25.BACKEND) (import-outside-toplevel)
tests/test_bm25.py:55:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_bm25.py:56:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:61:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:67:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:93:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:111:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:116:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:122:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:128:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:144:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:145:8: C0415: Import outside toplevel (_bm25.BM25) (import-outside-toplevel)
tests/test_bm25.py:154:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_bm25.py:158:12: C0415: Import outside toplevel (_bm25_ext) (import-outside-toplevel)
tests/test_bm25.py:162:8: C0415: Import outside toplevel (_bm25._fallback.BM25, _bm25._fallback.Document) (import-outside-toplevel)
tests/test_bm25.py:154:0: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_bm25.py:186:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_bm25.py:187:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:188:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_bm25.py:193:8: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_bm25.py:187:32: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_bm25.py:197:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:198:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_bm25.py:203:8: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_bm25.py:197:47: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_bm25.py:208:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:209:8: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_bm25.py:208:43: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_bm25.py:213:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:214:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_bm25.py:218:8: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_bm25.py:213:35: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_bm25.py:222:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_bm25.py:223:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_bm25.py:232:12: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_bm25.py:222:37: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
************* Module tests.test_classifier
tests/test_classifier.py:16:0: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:17:4: C0415: Import outside toplevel (orchestrator.classifier.classify) (import-outside-toplevel)
tests/test_classifier.py:21:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_classifier.py:22:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:22:37: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:27:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:27:38: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:31:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:31:44: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:36:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:36:43: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:40:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:40:48: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:45:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:45:37: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:50:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_classifier.py:51:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:51:53: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:56:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:56:50: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:60:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:60:50: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:65:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:65:45: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:70:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:70:45: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:74:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:74:39: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:79:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:79:46: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:83:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:83:44: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:88:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_classifier.py:89:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:89:29: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:93:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:93:33: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:97:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:97:43: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:101:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:101:34: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:105:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:105:47: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
tests/test_classifier.py:110:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_classifier.py:110:50: W0621: Redefining name 'classify' from outer scope (line 16) (redefined-outer-name)
************* Module tests.test_context_builder
tests/test_context_builder.py:26:4: C0415: Import outside toplevel (orchestrator.context_builder.ContextBundle) (import-outside-toplevel)
tests/test_context_builder.py:50:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:51:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:52:8: C0415: Import outside toplevel (orchestrator.context_builder._estimate_tokens) (import-outside-toplevel)
tests/test_context_builder.py:55:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:56:8: C0415: Import outside toplevel (orchestrator.context_builder._estimate_tokens) (import-outside-toplevel)
tests/test_context_builder.py:59:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:60:8: C0415: Import outside toplevel (orchestrator.context_builder._estimate_tokens) (import-outside-toplevel)
tests/test_context_builder.py:63:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:64:8: C0415: Import outside toplevel (orchestrator.context_builder._estimate_tokens) (import-outside-toplevel)
tests/test_context_builder.py:71:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:72:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:73:8: C0415: Import outside toplevel (orchestrator.context_builder.TIER_BUDGETS) (import-outside-toplevel)
tests/test_context_builder.py:76:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:77:8: C0415: Import outside toplevel (orchestrator.context_builder.TIER_BUDGETS) (import-outside-toplevel)
tests/test_context_builder.py:80:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:81:8: C0415: Import outside toplevel (orchestrator.context_builder.TIER_BUDGETS) (import-outside-toplevel)
tests/test_context_builder.py:88:8: C0415: Import outside toplevel (orchestrator.context_builder.build) (import-outside-toplevel)
tests/test_context_builder.py:92:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:94:8: C0415: Import outside toplevel (orchestrator.context_builder.build) (import-outside-toplevel)
tests/test_context_builder.py:103:8: W0108: Lambda may not be necessary (unnecessary-lambda)
tests/test_context_builder.py:107:8: W0108: Lambda may not be necessary (unnecessary-lambda)
tests/test_context_builder.py:136:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:137:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:138:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:148:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:149:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:158:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:161:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:173:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:189:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:204:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:207:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:220:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:231:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:234:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:252:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:266:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_context_builder.py:269:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget, orchestrator.context_builder._estimate_tokens) (import-outside-toplevel)
tests/test_context_builder.py:291:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:300:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_context_builder.py:301:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:309:8: C0415: Import outside toplevel (orchestrator.context_builder._trim_to_budget) (import-outside-toplevel)
tests/test_context_builder.py:14:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_doctor
tests/test_doctor.py:133:0: C0301: Line too long (103/100) (line-too-long)
tests/test_doctor.py:29:0: R0913: Too many arguments (8/5) (too-many-arguments)
tests/test_doctor.py:29:0: R0914: Too many local variables (33/15) (too-many-locals)
tests/test_doctor.py:44:4: C0415: Import outside toplevel (cli.main._cmd_doctor) (import-outside-toplevel)
tests/test_doctor.py:57:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:62:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:64:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:72:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:78:12: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:78:39: C0321: More than one statement on a single line (multiple-statements)
tests/test_doctor.py:79:12: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:79:39: C0321: More than one statement on a single line (multiple-statements)
tests/test_doctor.py:80:8: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:98:35: C0321: More than one statement on a single line (multiple-statements)
tests/test_doctor.py:99:8: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:99:24: C0321: More than one statement on a single line (multiple-statements)
tests/test_doctor.py:97:4: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_doctor.py:110:4: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:113:30: W0108: Lambda may not be necessary (unnecessary-lambda)
tests/test_doctor.py:119:8: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:120:23: C0321: More than one statement on a single line (multiple-statements)
tests/test_doctor.py:120:12: R0903: Too few public methods (0/2) (too-few-public-methods)
tests/test_doctor.py:118:4: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_doctor.py:122:26: W0108: Lambda may not be necessary (unnecessary-lambda)
tests/test_doctor.py:29:0: R0915: Too many statements (58/50) (too-many-statements)
tests/test_doctor.py:30:4: W0613: Unused argument 'capsys' (unused-argument)
tests/test_doctor.py:153:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:154:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:158:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:164:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:170:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:171:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:175:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:183:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:189:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:190:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:194:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:200:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:201:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:205:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:211:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:212:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:211:0: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_doctor.py:220:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_doctor.py:221:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_doctor.py:220:0: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_doctor.py:24:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_encryption
tests/test_encryption.py:21:0: R0402: Use 'from unittest import mock' instead (consider-using-from-import)
tests/test_encryption.py:38:9: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_encryption.py:28:23: W0613: Unused argument 'tmp_path' (unused-argument)
tests/test_encryption.py:52:9: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_encryption.py:42:24: W0613: Unused argument 'tmp_path' (unused-argument)
tests/test_encryption.py:61:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_encryption.py:63:8: C0415: Import outside toplevel (security.encryption.get_or_create_key, security.encryption.encrypt_bytes, security.encryption.decrypt_bytes) (import-outside-toplevel)
tests/test_encryption.py:77:8: C0415: Import outside toplevel (security.encryption.get_or_create_key) (import-outside-toplevel)
tests/test_encryption.py:81:21: W0613: Unused argument 'service' (unused-argument)
tests/test_encryption.py:81:30: W0613: Unused argument 'project_id' (unused-argument)
tests/test_encryption.py:85:21: W0613: Unused argument 'service' (unused-argument)
tests/test_encryption.py:85:30: W0613: Unused argument 'project_id' (unused-argument)
tests/test_encryption.py:105:8: C0415: Import outside toplevel (security.encryption) (import-outside-toplevel)
tests/test_encryption.py:107:12: W0212: Access to a protected member _require_deps of a client class (protected-access)
tests/test_encryption.py:112:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_encryption.py:113:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_encryption.py:119:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:122:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:127:12: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_encryption.py:142:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:145:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:150:12: C0415: Import outside toplevel (memory.episodic_memory) (import-outside-toplevel)
tests/test_encryption.py:152:12: C0415: Import outside toplevel (importlib) (import-outside-toplevel)
tests/test_encryption.py:163:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_encryption.py:173:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_encryption.py:174:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_encryption.py:180:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:183:21: W0613: Unused argument 'svc' (unused-argument)
tests/test_encryption.py:188:12: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_encryption.py:198:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_encryption.py:201:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_encryption.py:213:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_encryption.py:216:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_encryption.py:220:18: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_encryption.py:220:18: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_encryption.py:214:45: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_encryption.py:213:0: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_encryption.py:19:0: W0611: Unused import os (unused-import)
************* Module tests.test_graph
tests/test_graph.py:16:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_graph.py:17:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:18:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType) (import-outside-toplevel)
tests/test_graph.py:24:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:25:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType, graph.knowledge_graph.EdgeType) (import-outside-toplevel)
tests/test_graph.py:34:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:35:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType, graph.knowledge_graph.EdgeType) (import-outside-toplevel)
tests/test_graph.py:45:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:46:8: C0415: Import outside toplevel (sys) (import-outside-toplevel)
tests/test_graph.py:47:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType) (import-outside-toplevel)
tests/test_graph.py:53:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:54:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType, graph.knowledge_graph.EdgeType) (import-outside-toplevel)
tests/test_graph.py:67:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:68:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType, graph.knowledge_graph.EdgeType) (import-outside-toplevel)
tests/test_graph.py:80:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:81:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph, graph.knowledge_graph.NodeType) (import-outside-toplevel)
tests/test_graph.py:90:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_graph.py:91:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:92:8: C0415: Import outside toplevel (graph.graph_utils.extract_entities_from_text) (import-outside-toplevel)
tests/test_graph.py:97:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:98:8: C0415: Import outside toplevel (graph.graph_utils.extract_entities_from_text) (import-outside-toplevel)
tests/test_graph.py:102:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:103:8: C0415: Import outside toplevel (graph.graph_utils.format_subgraph_for_context) (import-outside-toplevel)
tests/test_graph.py:107:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_graph.py:108:8: C0415: Import outside toplevel (graph.graph_utils.format_subgraph_for_context) (import-outside-toplevel)
tests/test_graph.py:13:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_hybrid_retrieval
tests/test_hybrid_retrieval.py:19:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_hybrid_retrieval.py:20:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:21:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:26:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:31:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:32:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:36:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:43:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:44:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:49:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:56:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:61:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:62:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:67:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:68:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:72:8: C0415: Import outside toplevel (retrieval.hybrid.hybrid_retrieve) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:76:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:77:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:83:8: C0415: Import outside toplevel (retrieval.hybrid.HybridRetriever) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:90:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_hybrid_retrieval.py:91:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_hybrid_retrieval.py:92:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:97:8: C0415: Import outside toplevel (retrieval.hybrid.episodic_bm25_filter) (import-outside-toplevel)
tests/test_hybrid_retrieval.py:90:0: R0903: Too few public methods (1/2) (too-few-public-methods)
tests/test_hybrid_retrieval.py:16:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_indexer_multilang
tests/test_indexer_multilang.py:40:4: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_indexer_multilang.py:41:4: C0415: Import outside toplevel (indexer.ast_indexer.ASTIndexer) (import-outside-toplevel)
tests/test_indexer_multilang.py:42:4: C0415: Import outside toplevel (indexer.language_registry.clear_cache) (import-outside-toplevel)
tests/test_indexer_multilang.py:38:18: W0613: Unused argument 'isolated_cognirepo' (unused-argument)
tests/test_indexer_multilang.py:59:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:59:45: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:81:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:81:35: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:93:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:93:46: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:105:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:105:50: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:112:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:112:57: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:118:37: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:127:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:127:45: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:131:8: W0212: Access to a protected member _build_reverse_index of a client class (protected-access)
tests/test_indexer_multilang.py:140:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_indexer_multilang.py:141:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:141:41: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:158:36: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:168:8: W0212: Access to a protected member _build_reverse_index of a client class (protected-access)
tests/test_indexer_multilang.py:174:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:174:35: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:189:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_indexer_multilang.py:190:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:190:51: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:205:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:205:38: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:214:8: W0212: Access to a protected member _build_reverse_index of a client class (protected-access)
tests/test_indexer_multilang.py:221:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_indexer_multilang.py:224:8: C0415: Import outside toplevel (indexer.language_registry.supported_extensions, indexer.language_registry.clear_cache) (import-outside-toplevel)
tests/test_indexer_multilang.py:229:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:230:8: C0415: Import outside toplevel (indexer.language_registry._get_language, indexer.language_registry.clear_cache) (import-outside-toplevel)
tests/test_indexer_multilang.py:237:8: C0415: Import outside toplevel (importlib) (import-outside-toplevel)
tests/test_indexer_multilang.py:238:8: C0415: Import outside toplevel (indexer.language_registry.clear_cache) (import-outside-toplevel)
tests/test_indexer_multilang.py:250:8: C0415: Import outside toplevel (indexer.language_registry) (import-outside-toplevel)
tests/test_indexer_multilang.py:253:15: W0212: Access to a protected member _get_language of a client class (protected-access)
tests/test_indexer_multilang.py:256:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:257:8: C0415: Import outside toplevel (indexer.language_registry.is_supported, indexer.language_registry.clear_cache) (import-outside-toplevel)
tests/test_indexer_multilang.py:261:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:262:8: C0415: Import outside toplevel (indexer.language_registry.is_supported) (import-outside-toplevel)
tests/test_indexer_multilang.py:268:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_indexer_multilang.py:269:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:269:47: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:282:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:282:50: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:294:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_indexer_multilang.py:294:40: W0621: Redefining name 'fresh_indexer' from outer scope (line 38) (redefined-outer-name)
tests/test_indexer_multilang.py:28:0: W0611: Unused import os (unused-import)
************* Module tests.test_init_seed
tests/test_init_seed.py:117:0: C0301: Line too long (120/100) (line-too-long)
tests/test_init_seed.py:20:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_init_seed.py:21:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:22:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:26:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:27:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:29:18: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_init_seed.py:29:18: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_init_seed.py:34:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:35:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:38:25: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_init_seed.py:38:25: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_init_seed.py:44:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:45:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:51:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:53:32: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_init_seed.py:53:32: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_init_seed.py:55:31: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_init_seed.py:55:31: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_init_seed.py:60:8: R0402: Use 'from unittest import mock' instead (consider-using-from-import)
tests/test_init_seed.py:60:8: C0415: Import outside toplevel (unittest.mock) (import-outside-toplevel)
tests/test_init_seed.py:61:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:67:25: R1732: Consider using 'with' for resource-allocating operations (consider-using-with)
tests/test_init_seed.py:67:25: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_init_seed.py:58:63: W0613: Unused argument 'monkeypatch' (unused-argument)
tests/test_init_seed.py:71:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:72:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:77:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:78:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:83:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:84:8: C0415: Import outside toplevel (cli.init_project.init_project) (import-outside-toplevel)
tests/test_init_seed.py:92:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_init_seed.py:93:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:94:8: C0415: Import outside toplevel (cli.seed.seed_from_git_log) (import-outside-toplevel)
tests/test_init_seed.py:104:8: C0415: Import outside toplevel (cli.seed.seed_from_git_log) (import-outside-toplevel)
tests/test_init_seed.py:109:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:110:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_init_seed.py:111:8: C0415: Import outside toplevel (graph.behaviour_tracker.BehaviourTracker) (import-outside-toplevel)
tests/test_init_seed.py:112:8: C0415: Import outside toplevel (cli.seed.seed_from_git_log) (import-outside-toplevel)
tests/test_init_seed.py:122:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_init_seed.py:123:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_init_seed.py:124:8: C0415: Import outside toplevel (graph.behaviour_tracker.BehaviourTracker) (import-outside-toplevel)
tests/test_init_seed.py:125:8: C0415: Import outside toplevel (cli.seed.seed_from_git_log) (import-outside-toplevel)
tests/test_init_seed.py:135:8: C0415: Import outside toplevel (subprocess) (import-outside-toplevel)
tests/test_init_seed.py:137:15: W1510: 'subprocess.run' used without explicitly defining the value for 'check'. (subprocess-run-check)
tests/test_init_seed.py:144:8: C0415: Import outside toplevel (graph.knowledge_graph.KnowledgeGraph) (import-outside-toplevel)
tests/test_init_seed.py:145:8: C0415: Import outside toplevel (graph.behaviour_tracker.BehaviourTracker) (import-outside-toplevel)
tests/test_init_seed.py:146:8: C0415: Import outside toplevel (indexer.ast_indexer.ASTIndexer) (import-outside-toplevel)
tests/test_init_seed.py:147:8: C0415: Import outside toplevel (cli.seed.seed_from_git_log) (import-outside-toplevel)
tests/test_init_seed.py:150:8: C0415: Import outside toplevel (pathlib) (import-outside-toplevel)
************* Module tests.test_mcp_server
tests/test_mcp_server.py:21:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_mcp_server.py:22:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:23:8: C0415: Import outside toplevel (tools.store_memory.store_memory) (import-outside-toplevel)
tests/test_mcp_server.py:29:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:30:8: C0415: Import outside toplevel (tools.store_memory.store_memory) (import-outside-toplevel)
tests/test_mcp_server.py:31:8: C0415: Import outside toplevel (tools.retrieve_memory.retrieve_memory) (import-outside-toplevel)
tests/test_mcp_server.py:36:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:37:8: C0415: Import outside toplevel (tools.retrieve_memory.retrieve_memory) (import-outside-toplevel)
tests/test_mcp_server.py:41:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:42:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_mcp_server.py:48:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:49:8: C0415: Import outside toplevel (importlib.util) (import-outside-toplevel)
tests/test_mcp_server.py:50:8: C0415: Import outside toplevel (server.mcp_server._write_manifest, server.mcp_server._build_manifest) (import-outside-toplevel)
tests/test_mcp_server.py:53:8: C0415: Import outside toplevel (server.mcp_server) (import-outside-toplevel)
tests/test_mcp_server.py:49:8: W0611: Unused import importlib.util (unused-import)
tests/test_mcp_server.py:63:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:64:8: C0415: Import outside toplevel (tools.store_memory.store_memory) (import-outside-toplevel)
tests/test_mcp_server.py:68:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:69:8: C0415: Import outside toplevel (tools.store_memory.store_memory) (import-outside-toplevel)
tests/test_mcp_server.py:76:4: C0415: Import outside toplevel (server.mcp_server._get_graph) (import-outside-toplevel)
tests/test_mcp_server.py:86:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_mcp_server.py:87:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:88:8: C0415: Import outside toplevel (server.mcp_server.lookup_symbol) (import-outside-toplevel)
tests/test_mcp_server.py:96:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:97:8: C0415: Import outside toplevel (server.mcp_server.lookup_symbol) (import-outside-toplevel)
tests/test_mcp_server.py:108:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:109:8: C0415: Import outside toplevel (server.mcp_server.who_calls) (import-outside-toplevel)
tests/test_mcp_server.py:118:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:119:8: C0415: Import outside toplevel (server.mcp_server.who_calls) (import-outside-toplevel)
tests/test_mcp_server.py:130:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:131:8: C0415: Import outside toplevel (server.mcp_server.subgraph) (import-outside-toplevel)
tests/test_mcp_server.py:141:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:142:8: C0415: Import outside toplevel (server.mcp_server.subgraph) (import-outside-toplevel)
tests/test_mcp_server.py:151:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:152:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_mcp_server.py:153:8: C0415: Import outside toplevel (server.mcp_server.episodic_search) (import-outside-toplevel)
tests/test_mcp_server.py:158:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:159:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_mcp_server.py:160:8: C0415: Import outside toplevel (server.mcp_server.episodic_search) (import-outside-toplevel)
tests/test_mcp_server.py:166:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:167:8: C0415: Import outside toplevel (memory.episodic_memory.log_event) (import-outside-toplevel)
tests/test_mcp_server.py:168:8: C0415: Import outside toplevel (server.mcp_server.episodic_search) (import-outside-toplevel)
tests/test_mcp_server.py:174:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:175:8: C0415: Import outside toplevel (server.mcp_server.graph_stats) (import-outside-toplevel)
tests/test_mcp_server.py:183:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:184:8: C0415: Import outside toplevel (server.mcp_server.graph_stats) (import-outside-toplevel)
tests/test_mcp_server.py:189:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:190:8: C0415: Import outside toplevel (server.mcp_server.graph_stats) (import-outside-toplevel)
tests/test_mcp_server.py:194:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:195:8: C0415: Import outside toplevel (server.mcp_server._build_manifest) (import-outside-toplevel)
tests/test_mcp_server.py:205:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:206:8: C0415: Import outside toplevel (server.mcp_server.lookup_symbol, server.mcp_server._get_graph) (import-outside-toplevel)
tests/test_mcp_server.py:216:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:217:8: C0415: Import outside toplevel (server.mcp_server.who_calls) (import-outside-toplevel)
tests/test_mcp_server.py:222:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:223:8: C0415: Import outside toplevel (server.mcp_server.subgraph) (import-outside-toplevel)
tests/test_mcp_server.py:228:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:229:8: C0415: Import outside toplevel (server.mcp_server.lookup_symbol) (import-outside-toplevel)
tests/test_mcp_server.py:233:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:234:8: C0415: Import outside toplevel (server.mcp_server.lookup_symbol, server.mcp_server._get_graph) (import-outside-toplevel)
tests/test_mcp_server.py:245:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_mcp_server.py:246:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:247:8: C0415: Import outside toplevel (server.mcp_server._build_manifest) (import-outside-toplevel)
tests/test_mcp_server.py:253:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_mcp_server.py:261:8: W0621: Redefining name 'os' from outer scope (line 16) (redefined-outer-name)
tests/test_mcp_server.py:254:8: C0415: Import outside toplevel (server.mcp_server._write_manifest) (import-outside-toplevel)
tests/test_mcp_server.py:256:8: C0415: Import outside toplevel (adapters.openai_spec.export) (import-outside-toplevel)
tests/test_mcp_server.py:258:8: C0415: Import outside toplevel (server.mcp_server) (import-outside-toplevel)
tests/test_mcp_server.py:259:8: C0415: Import outside toplevel (adapters.openai_spec) (import-outside-toplevel)
tests/test_mcp_server.py:261:8: W0404: Reimport 'os' (imported line 16) (reimported)
tests/test_mcp_server.py:261:8: C0415: Import outside toplevel (os) (import-outside-toplevel)
tests/test_mcp_server.py:268:13: W1514: Using open without explicitly specifying an encoding (unspecified-encoding)
tests/test_mcp_server.py:18:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_memory
tests/test_memory.py:18:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_memory.py:19:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:20:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_memory.py:27:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:28:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_memory.py:34:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:35:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_memory.py:50:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:51:8: C0415: Import outside toplevel (memory.semantic_memory.SemanticMemory) (import-outside-toplevel)
tests/test_memory.py:59:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_memory.py:60:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:61:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_memory.py:68:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:69:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_memory.py:80:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:81:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_memory.py:87:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:88:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_memory.py:94:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_memory.py:95:8: C0415: Import outside toplevel (memory.episodic_memory.log_event, memory.episodic_memory.get_history) (import-outside-toplevel)
tests/test_memory.py:12:0: W0611: Unused import json (unused-import)
tests/test_memory.py:13:0: W0611: Unused import os (unused-import)
tests/test_memory.py:15:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_router
tests/test_router.py:29:4: C0415: Import outside toplevel (orchestrator.router.try_local_resolve) (import-outside-toplevel)
tests/test_router.py:35:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:36:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:42:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:47:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:52:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:59:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:60:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:66:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:71:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:78:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:79:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:84:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:89:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:94:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:101:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:102:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:107:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:112:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:120:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:121:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:126:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:131:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:139:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_router.py:140:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:143:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:146:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:149:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_router.py:17:0: W0611: Unused import pytest (unused-import)
************* Module tests.test_session
tests/test_session.py:27:4: C0415: Import outside toplevel (orchestrator.session) (import-outside-toplevel)
tests/test_session.py:38:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_session.py:39:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:40:8: C0415: Import outside toplevel (orchestrator.session.create_session) (import-outside-toplevel)
tests/test_session.py:46:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:47:8: C0415: Import outside toplevel (orchestrator.session) (import-outside-toplevel)
tests/test_session.py:48:8: C0415: Import outside toplevel (orchestrator.session.create_session) (import-outside-toplevel)
tests/test_session.py:50:15: W0212: Access to a protected member _SESSIONS_DIR of a client class (protected-access)
tests/test_session.py:53:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:54:8: C0415: Import outside toplevel (orchestrator.session) (import-outside-toplevel)
tests/test_session.py:55:8: C0415: Import outside toplevel (orchestrator.session.create_session) (import-outside-toplevel)
tests/test_session.py:57:15: W0212: Access to a protected member _CURRENT_PTR of a client class (protected-access)
tests/test_session.py:58:25: W0212: Access to a protected member _CURRENT_PTR of a client class (protected-access)
tests/test_session.py:61:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:62:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.load_session) (import-outside-toplevel)
tests/test_session.py:68:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:69:8: C0415: Import outside toplevel (orchestrator.session.load_session) (import-outside-toplevel)
tests/test_session.py:72:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:73:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.load_current_session) (import-outside-toplevel)
tests/test_session.py:79:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:80:8: C0415: Import outside toplevel (orchestrator.session.load_current_session) (import-outside-toplevel)
tests/test_session.py:83:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:84:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.load_session) (import-outside-toplevel)
tests/test_session.py:92:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_session.py:93:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:94:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.find_session) (import-outside-toplevel)
tests/test_session.py:99:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:100:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.find_session) (import-outside-toplevel)
tests/test_session.py:107:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:108:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.find_session) (import-outside-toplevel)
tests/test_session.py:116:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:117:8: C0415: Import outside toplevel (orchestrator.session.find_session) (import-outside-toplevel)
tests/test_session.py:123:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_session.py:124:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:125:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:132:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:133:8: C0415: Import outside toplevel (orchestrator.session) (import-outside-toplevel)
tests/test_session.py:134:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange, orchestrator.session.load_session) (import-outside-toplevel)
tests/test_session.py:140:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:141:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:149:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:158:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:171:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:182:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:191:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:203:0: C0115: Missing class docstring (missing-class-docstring)
tests/test_session.py:204:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:205:8: C0415: Import outside toplevel (orchestrator.session.list_sessions) (import-outside-toplevel)
tests/test_session.py:206:15: C1803: "list_sessions(...) == []" can be simplified to "not list_sessions(...)", if it is strictly a sequence, as an empty list is falsey (use-implicit-booleaness-not-comparison)
tests/test_session.py:208:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:209:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.list_sessions) (import-outside-toplevel)
tests/test_session.py:217:8: C0415: Import outside toplevel (time) (import-outside-toplevel)
tests/test_session.py:218:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.list_sessions, orchestrator.session.append_exchange) (import-outside-toplevel)
tests/test_session.py:228:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:229:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.list_sessions) (import-outside-toplevel)
tests/test_session.py:234:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:235:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.list_sessions) (import-outside-toplevel)
tests/test_session.py:240:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:241:8: C0415: Import outside toplevel (orchestrator.session.create_session, orchestrator.session.current_session_id) (import-outside-toplevel)
tests/test_session.py:253:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:255:8: C0415: Import outside toplevel (unittest.mock.MagicMock, unittest.mock.patch) (import-outside-toplevel)
tests/test_session.py:276:12: C0415: Import outside toplevel (orchestrator.model_adapters.anthropic_adapter) (import-outside-toplevel)
tests/test_session.py:284:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:286:8: C0415: Import outside toplevel (unittest.mock.MagicMock, unittest.mock.patch) (import-outside-toplevel)
tests/test_session.py:308:12: C0415: Import outside toplevel (orchestrator.model_adapters.openai_adapter) (import-outside-toplevel)
tests/test_session.py:316:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:317:8: C0415: Import outside toplevel (orchestrator.model_adapters.gemini_adapter._build_contents) (import-outside-toplevel)
tests/test_session.py:330:4: C0116: Missing function or method docstring (missing-function-docstring)
tests/test_session.py:331:8: C0415: Import outside toplevel (orchestrator.model_adapters.gemini_adapter._build_contents) (import-outside-toplevel)
tests/test_session.py:16:0: W0611: Unused import os (unused-import)
tests/test_session.py:17:0: W0611: Unused Path imported from pathlib (unused-import)
************* Module tools.__init__
tools/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module vector_db.__init__
vector_db/__init__.py:6:0: C0305: Trailing newlines (trailing-newlines)
************* Module vector_db.local_vector_db
vector_db/local_vector_db.py:111:15: R1716: Simplify chained comparison between the operands (chained-comparison)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==api.routes.graph:[61:117]
==server.mcp_server:[81:138]
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    indexer = _get_indexer()
    locations = indexer.lookup_symbol(name)
    result = []
    for loc in locations:
        file_path = loc["file"]
        line = loc["line"]
        sym_type = "UNKNOWN"
        file_data = indexer.index_data["files"].get(file_path, {})
        for sym in file_data.get("symbols", []):
            if sym["name"] == name and sym["start_line"] == line:
                sym_type = sym["type"]
                break
        result.append({"file": file_path, "line": line, "type": sym_type})
    return result


@router.get("/callers/{function_name}")
def callers(function_name: str):
    """Return every caller of *function_name* across the indexed repo."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    graph = _get_graph()
    callee_node = f"symbol::{function_name}"
    if not graph.node_exists(callee_node):
        return []
    result = []
    for caller in graph.G.predecessors(callee_node):
        edge_data = graph.G[caller][callee_node]
        if edge_data.get("rel") == EdgeType.CALLED_BY:
            node_data = dict(graph.G.nodes[caller])
            result.append({
                "caller": caller,
                "file": node_data.get("file", ""),
                "line": node_data.get("line", -1),
            })
    return result


@router.get("/subgraph/{entity}")
def subgraph(entity: str, depth: int = Query(default=2, ge=1, le=5)):
    """Return the ego-graph around *entity* as {nodes, edges}."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    graph = _get_graph()
    candidates = [entity, f"symbol::{entity}", f"concept::{entity.lower()}"]
    for candidate in candidates:
        if graph.node_exists(candidate):
            return graph.subgraph_around(candidate, radius=depth)
    return {"nodes": [], "edges": []}


@router.get("/stats")
def stats():
    """Return a health summary of the current graph state.""" (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==api.routes.graph:[25:61]
==server.mcp_server:[22:56]
_graph = None
_indexer = None


def _get_graph():
    global _graph
    if _graph is None:
        from graph.knowledge_graph import KnowledgeGraph
        _graph = KnowledgeGraph()
    return _graph


def _get_indexer():
    global _indexer
    if _indexer is None:
        from indexer.ast_indexer import ASTIndexer
        _indexer = ASTIndexer(_get_graph())
        _indexer.load()
    return _indexer


_EMPTY_GRAPH_WARNING = {
    "warning": "Graph is empty. Run 'cognirepo index-repo .' first.",
    "results": [],
}


def _graph_is_empty() -> bool:
    return _get_graph().G.number_of_nodes() == 0


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/symbol/{name}")
def symbol_lookup(name: str):
    """Return all locations where *name* is defined, with file, line, and type.""" (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==api.routes.graph:[119:133]
==server.mcp_server:[154:168]
    concept_nodes = [
        n for n, d in graph.G.nodes(data=True) if d.get("type") == "CONCEPT"
    ]
    top_concepts = sorted(
        concept_nodes,
        key=lambda n: graph.G.degree(n),
        reverse=True,
    )[:5]
    last_indexed = None
    ast_index_path = ".cognirepo/index/ast_index.json"
    if os.path.exists(ast_index_path):
        with open(ast_index_path, encoding="utf-8") as f:
            last_indexed = json.load(f).get("indexed_at")
    return { (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==orchestrator.model_adapters.anthropic_adapter:[169:182]
==orchestrator.model_adapters.openai_adapter:[203:216]
    return usage  # becomes StopIteration.value


def _manifest_to_openai_tools(manifest: list[dict]) -> list[dict]:
    """Convert CogniRepo manifest entries to OpenAI tool definitions."""
    tools = []
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue
        tools.append({ (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==api.routes.episodic:[48:56]
==server.mcp_server:[139:152]
    events = get_history(limit=10000)
    matches = []
    for event in events:
        if query_lower in json.dumps(event).lower():
            matches.append(event)
            if len(matches) >= limit:
                break
    return matches


@mcp.tool()
def graph_stats() -> dict:
    """Return a health summary of the current graph state.""" (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==api.auth:[39:48]
==security.__init__:[24:37]
            return json.load(f).get(
                "project_id",
                os.path.basename(os.path.abspath(os.getcwd())),
            )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return os.path.basename(os.path.abspath(os.getcwd()))


def get_storage_config() -> tuple[bool, str]:
    """
    Return (should_encrypt, project_id) from .cognirepo/config.json.
    Returns (False, "") when the config is absent or encryption is disabled.
    """ (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==memory.episodic_memory:[22:34]
==vector_db.local_vector_db:[44:55]
            raw = f.read()
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        if encrypt:
            from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
            raw = decrypt_bytes(raw, get_or_create_key(project_id))
        return json.loads(raw)

    def _save_meta(self) -> None:
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config() (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==orchestrator.model_adapters.anthropic_adapter:[175:181]
==orchestrator.model_adapters.gemini_adapter:[250:256]
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue (duplicate-code)
vector_db/local_vector_db.py:1:0: R0801: Similar lines in 2 files
==tests.test_bm25:[188:198]
==tests.test_hybrid_retrieval:[92:100]
        log_event("deployed auth service to production", {"env": "prod"})
        log_event("fixed bug in payment module", {"module": "payments"})
        log_event("updated JWT expiry to 24 hours", {"service": "auth"})

        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT auth", top_k=2)
        assert isinstance(results, list)
        # JWT-related event should appear (duplicate-code)

-----------------------------------
Your code has been rated at 7.79/10



3. Bandit 
Run bandit -r cognirepo/ adapters/ api/ cli/ cron/ graph/ indexer/ \
usage: bandit [-h] [-r] [-a {file,vuln}] [-n CONTEXT_LINES] [-c CONFIG_FILE]
              [-p PROFILE] [-t TESTS] [-s SKIPS]
              [-l | --severity-level {all,low,medium,high}]
              [-i | --confidence-level {all,low,medium,high}]
              [-f {csv,custom,html,json,screen,txt,xml,yaml}]
              [--msg-template MSG_TEMPLATE] [-o [OUTPUT_FILE]] [-v] [-d] [-q]
              [--ignore-nosec] [-x EXCLUDED_PATHS] [-b BASELINE]
              [--ini INI_PATH] [--exit-zero] [--version]
              [targets ...]
bandit: error: unrecognized arguments: --exit-zero-on-skipped



4. snyk issues:
Run snyk/actions/python@master
/usr/bin/docker run --name snyksnykpython_e02f4a --label 6a443b --workdir /github/workspace --rm -e "SNYK_TOKEN" -e "INPUT_ARGS" -e "INPUT_COMMAND" -e "INPUT_JSON" -e "FORCE_COLOR" -e "SNYK_INTEGRATION_NAME" -e "SNYK_INTEGRATION_VERSION" -e "HOME" -e "GITHUB_JOB" -e "GITHUB_REF" -e "GITHUB_SHA" -e "GITHUB_REPOSITORY" -e "GITHUB_REPOSITORY_OWNER" -e "GITHUB_REPOSITORY_OWNER_ID" -e "GITHUB_RUN_ID" -e "GITHUB_RUN_NUMBER" -e "GITHUB_RETENTION_DAYS" -e "GITHUB_RUN_ATTEMPT" -e "GITHUB_ACTOR_ID" -e "GITHUB_ACTOR" -e "GITHUB_WORKFLOW" -e "GITHUB_HEAD_REF" -e "GITHUB_BASE_REF" -e "GITHUB_EVENT_NAME" -e "GITHUB_SERVER_URL" -e "GITHUB_API_URL" -e "GITHUB_GRAPHQL_URL" -e "GITHUB_REF_NAME" -e "GITHUB_REF_PROTECTED" -e "GITHUB_REF_TYPE" -e "GITHUB_WORKFLOW_REF" -e "GITHUB_WORKFLOW_SHA" -e "GITHUB_REPOSITORY_ID" -e "GITHUB_TRIGGERING_ACTOR" -e "GITHUB_WORKSPACE" -e "GITHUB_ACTION" -e "GITHUB_EVENT_PATH" -e "GITHUB_ACTION_REPOSITORY" -e "GITHUB_ACTION_REF" -e "GITHUB_PATH" -e "GITHUB_ENV" -e "GITHUB_STEP_SUMMARY" -e "GITHUB_STATE" -e "GITHUB_OUTPUT" -e "RUNNER_OS" -e "RUNNER_ARCH" -e "RUNNER_NAME" -e "RUNNER_ENVIRONMENT" -e "RUNNER_TOOL_CACHE" -e "RUNNER_TEMP" -e "RUNNER_WORKSPACE" -e "ACTIONS_RUNTIME_URL" -e "ACTIONS_RUNTIME_TOKEN" -e "ACTIONS_CACHE_URL" -e "ACTIONS_RESULTS_URL" -e "ACTIONS_ORCHESTRATION_ID" -e GITHUB_ACTIONS=true -e CI=true -v "/var/run/docker.sock":"/var/run/docker.sock" -v "/home/runner/work/_temp":"/github/runner_temp" -v "/home/runner/work/_temp/_github_home":"/github/home" -v "/home/runner/work/_temp/_github_workflow":"/github/workflow" -v "/home/runner/work/_temp/_runner_file_commands":"/github/file_commands" -v "/home/runner/work/cognirepo/cognirepo":"/github/workspace" snyk/snyk:python  "snyk" "test" "--file=pyproject.toml --severity-threshold=high"
Skipping virtualenv creation, as specified in config file.

The current project's supported Python range (>=3.11) is not compatible with some of the required packages Python requirement:
  - faiss-cpu requires Python <3.15,>=3.10, so it will not be installable for Python >=3.15

Because cognirepo depends on faiss-cpu (1.13.2) which requires Python <3.15,>=3.10, version solving failed.

  * Check your dependencies Python requirement: The Python requirement can be specified via the `python` or `markers` properties

    For faiss-cpu, a possible solution would be to set the `python` property to ">=3.11,<3.15"

    https://python-poetry.org/docs/dependency-specification/#python-restricted-dependencies,
    https://python-poetry.org/docs/dependency-specification/#using-environment-markers


 ERROR   Unspecified Error (SNYK-CLI-0000)
                                                                                        
                                                                                        
           Testing /github/workspace...                                                 
                                                                                        
           Could not detect package manager for file: pyproject.toml                    

Docs:    https://docs.snyk.io/scan-with-snyk/error-catalog#snyk-cli-0000 
                                                                         
ID:      urn:snyk:interaction:aebc36f5-1544-4da7-8347-4689b812a536 