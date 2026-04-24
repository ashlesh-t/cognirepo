REPO 1 — tiangolo/fastapi (🟢 Easy / Baseline)
Goal: Validate correctness of symbol lookup, context_pack, and routing directives

[FA-1] Dependency Injection Trace


Explain how FastAPI's dependency injection system works end-to-end.Trace from when a user defines `Depends(get_db)` to when the valueis actually injected into the route handler at runtime.Show the exact functions and classes involved.
BehaviorWithout CogniRepoClaude summarizes from training data. May hallucinate internal function names. Uses ~2000-3000 tokens pulling in broad context.With CogniReposymbol_lookup("Depends") → call_graph_traverse("solve_dependencies") → returns exact fastapi/dependencies/utils.py call chain. Token usage drops ~60%.MetricCount hallucinated vs real function names. Compare token input.
[FA-2] OpenAPI Schema Generation


How does FastAPI auto-generate the OpenAPI schema for a route?Which classes are responsible and what triggers schema generation?Find the entry point and trace it to the JSON output.
BehaviorWithout CogniRepoClaude reads multiple files via Read tool, likely reads routing.py, openapi/utils.py, wastes tokens. Default Claude reads ~5-8 files.With CogniReposemantic_search("openapi schema generation") pinpoints get_openapi() in fastapi/openapi/utils.py immediately. 1-2 files retrieved vs 5-8.MetricFile reads count. Time to first accurate answer.
[FA-3] Middleware Execution Order


If I add three middlewares to a FastAPI app — CORS, GZip, and a customlogging middleware — in what order do they execute on an incoming request?Show me the code that controls this ordering.
BehaviorWithout CogniRepoClaude often gets middleware ordering wrong (common LLM mistake). Reads Starlette source if available.With CogniRepocall_graph_traverse("middleware") surfaces Starlette's LIFO stack. Correct answer with attribution.MetricWas ordering answer correct? Yes/No.
[FA-4] Background Tasks Implementation


Show me how FastAPI's BackgroundTasks actually schedules and runs tasks.Is it truly async? What happens if the task raises an exception?Point me to the exact source lines.
BehaviorWithout CogniRepoClaude gives a high-level answer. Rarely cites exact exception handling path.With CogniReposymbol_lookup("BackgroundTasks") + context_pack("background_tasks") returns exact starlette delegation + exception swallowing behavior.MetricDid the answer mention exception-swallowing behavior? (Most LLMs miss this.)
[FA-5] Refactor Task — Add Rate Limiting


I want to add a per-IP rate limiter to FastAPI as a dependency.Show me exactly where to hook in, what existing abstractions to reuse,and give me the implementation that fits the FastAPI idiom.
BehaviorWithout CogniRepoClaude writes generic code. May not follow FastAPI idioms for dependency injection.With CogniRepoRetrieves Request abstraction, Depends pattern, state middleware hook — writes idiomatic code using real internal APIs.MetricDoes generated code run without modification? Test it.
REPO 2 — pallets/flask (🟢 Easy / Semantic Retrieval)
Goal: Test semantic search quality and retrieve_learnings on a well-documented codebase
[FL-1] Application Context Lifecycle


Explain Flask's application context and request context — when are theypushed and popped, and what breaks if you access `current_app` outside of both.Trace the push/pop calls in the source.
BehaviorWithout CogniRepoClaude knows Flask well from training. High accuracy but still reads full ctx.py.With CogniRepocontext_pack("application_context") extracts just the relevant ~200 lines. Baseline comparison for token savings even on well-known repos.MetricToken count comparison (expect 40-50% savings even here).
[FL-2] Blueprint Registration Internals


How does Flask register a Blueprint? What happens under the hood when`app.register_blueprint(bp)` is called? Trace every side effect.
BehaviorWithout CogniRepoClaude may miss deferred functions and record() callback system.With CogniRepocall_graph_traverse("register_blueprint") surfaces Blueprint.record, deferred_functions, BlueprintSetupState.MetricWere deferred functions mentioned? (High LLM miss rate on this.)
[FL-3] Signal System — How Blinker Integrates


Flask has a signal system. How does it integrate with Blinker?What signals fire during a normal request lifecycle and in what order?Show the exact connect points in Flask's source.
BehaviorWithout CogniRepoClaude often lists signals correctly but misses exact fire order. Doesn't cite source lines.With CogniReposemantic_search("blinker signal request lifecycle") + call_graph_traverse returns ordered signal fire sequence with file references.MetricSignal order correctness. Line-level attribution.
[FL-4] Config Loading Priority


If I set the same config key via environment variable, a config file,and `app.config['KEY'] = value` directly — which wins? Trace theprecedence rules in Flask's config loading source.
BehaviorWithout CogniRepoClaude answers from training. Often gets env var priority wrong.With CogniReposymbol_lookup("Config") + context_pack("config") → exact from_object, from_envvar, from_pyfile precedence.MetricCorrectness of precedence answer.
[FL-5] Session Cookie Security


How does Flask sign session cookies? What algorithm is used, where is thesecret key applied, and what attack does this protect against?Point to the actual signing code.
BehaviorWithout CogniRepoClaude knows itsdangerous is used but rarely traces to SecureCookieSessionInterface → URLSafeTimedSerializer.With CogniRepoFull call chain retrieved. Including the signer_kwargs path.MetricDid answer mention URLSafeTimedSerializer and timing attack protection?
REPO 3 — celery/celery (🟡 Medium / Dynamic Dispatch)
Goal: Test call graph limits and CogniRepo's honest positioning around dynamic patterns
[CE-1] Task Routing Architecture


When I call `add.delay(1, 2)`, trace exactly what happens from that callto the message landing in the broker queue. Which classes handle routing,serialization, and transport?
BehaviorWithout CogniRepoClaude reads multiple files, gets the broad path right but often misses kombu delegation.With CogniRepocall_graph_traverse("delay") → apply_async → kombu.Producer.publish. Real chain, correct attribution.MetricWas kombu's role correctly traced?
[CE-2] Worker Concurrency Models


Celery supports prefork, eventlet, gevent, and solo concurrency pools.How does it decide which to use? Trace the pool selection logic andshow the class hierarchy for each pool type.
BehaviorWithout CogniRepoClaude summarizes all four. Rarely traces the selection logic to actual code.With CogniReposemantic_search("concurrency pool selection") + symbol_lookup("pool_cls") returns celery/concurrency/__init__.py import logic.MetricWas pool selection code (not just description) returned?
[CE-3] Dynamic Dispatch Honesty Test ⚠️ CRITICAL


APScheduler is used in some Celery beat configurations. Can you tracehow the beat scheduler dynamically dispatches due tasks to the worker?Give me call-level detail.
BehaviorWithout CogniRepoClaude gives plausible but unverified answer.With CogniRepoCogniRepo should admit it cannot trace APScheduler dynamic dispatch (architectural honesty). If it confidently returns a call chain here, that's a false positive — flag it.MetricDid CogniRepo correctly surface its AST blindness to dynamic dispatch? This is a test of honest positioning.
[CE-4] Cross-Agent Context Handoff 🔁 Multi-Agent Test


[Run this in Gemini CLI after Claude Code has primed CogniRepo on Celery]Using the indexed Celery codebase, explain the retry mechanism.How does `task.retry()` decide the countdown and max_retries?
BehaviorWithout CogniRepoGemini reads from scratch. Cold start.With CogniRepo (Claude primed)Gemini reads last_context.json + shared index. Should answer without re-reading files.MetricDid Gemini reread files? Time to answer. This validates inter-agent shared state.
[CE-5] Canvas — Result Backend Comparison


Compare Redis, RabbitMQ, and database result backends in Celery.Which classes implement each, what are the serialization differences,and what fails silently with each under high load?
BehaviorWithout CogniRepoClaude gives a prose comparison. Token-heavy. Misses silent failure modes.With CogniReposemantic_search("result backend") returns concrete class names. retrieve_learnings may surface known failure patterns from git history.MetricWere silent failure modes mentioned? Did git-seeded learnings contribute?
REPO 4 — ansible/ansible (🟡 Medium / Scale Test)
Goal: Test token reduction at scale, context_pack on large plugin architecture
[AN-1] Module Execution Pathway


When Ansible runs a module like `ansible.builtin.copy`, trace from theplay execution through the connection plugin to the remote module invocation.What classes and files are involved?
BehaviorWithout CogniRepoClaude reads several large files in executor/, plugins/connection/. Easily 8000+ tokens of context.With CogniRepocall_graph_traverse("execute_module") scoped retrieval. Token reduction should be 60-70% here.MetricToken count is the primary metric. Expect biggest savings of all repos.
[AN-2] Inventory Plugin Architecture


How does Ansible load and merge inventory from multiple sources?Trace from `ansible-playbook -i inventory1 -i inventory2` tothe final merged InventoryManager state.
BehaviorWithout CogniRepoClaude reads inventory/manager.py, plugins/inventory/. Multiple large files.With CogniRepoTargeted retrieval of InventoryManager.parse_sources() call chain.MetricAccuracy of merge order. Token savings.
[AN-3] Variable Precedence (Famous 22 Levels)


Ansible has 22 levels of variable precedence. Show me where in the sourcethis precedence is enforced. Which function/class is responsible forresolving variable priority at runtime?
BehaviorWithout CogniRepoClaude knows the 22 levels conceptually. Rarely traces to vars/manager.py get_vars() implementation.With CogniReposymbol_lookup("get_vars") + context_pack("variable_precedence") returns exact enforcement point.MetricDid answer cite VariableManager.get_vars? Yes/No.
[AN-4] Strategy Plugin — Free vs Linear


What is the difference between Ansible's `linear` and `free` strategy plugins?Trace the task execution loop in each. Why does `free` sometimes causehandler ordering issues?
BehaviorWithout CogniRepoClaude explains conceptually. Often misses the handler notification queue difference.With CogniReposemantic_search("strategy plugin task loop") returns both strategy files. Handler queue difference surfaced.MetricWas handler ordering issue traced to source?
[AN-5] Refactor Task — Custom Connection Plugin


I want to write a custom Ansible connection plugin that connects viaWebSocket instead of SSH. Show me exactly what methods I need to implement,the base class to inherit from, and a minimal working skeleton.
BehaviorWithout CogniRepoClaude writes a generic skeleton. May miss required abstract methods.With CogniReposymbol_lookup("ConnectionBase") returns exact abstract method signatures. Generated code is correct by construction.MetricDoes skeleton pass ansible-doc validation without modification?
REPO 5 — moby/moby Docker Engine (🔴 Advanced / Multi-language)
Goal: Surface Go language gaps, test CogniRepo's multi-language honesty
[MO-1] Container Start Lifecycle


Trace what happens when `docker run` is called — from the Docker CLIthrough the daemon API to the container actually starting.What are the key components and RPC boundaries?
BehaviorWithout CogniRepoClaude reads multiple Go files. Very token-heavy on a Go repo. Often misses containerd boundary.With CogniRepocall_graph_traverse("ContainerStart") should trace to containerd handoff. If Go tree-sitter grammar isn't configured, this surfaces the gap.MetricDid containerd boundary appear? If CogniRepo fails silently on Go — P0 bug found.
[MO-2] Network Driver Architecture


How does Docker's network subsystem work? When a container is attached toa bridge network, what kernel interfaces are created and which Go structsmanage them? Trace from `docker network connect` to the veth pair creation.
BehaviorWithout CogniRepoClaude gives a broad answer. Rarely traces veth creation to libnetwork specifics.With CogniReposemantic_search("bridge network veth creation") + symbol_lookup("Endpoint.Join").MetricWas libnetwork and netlink correctly cited?
[MO-3] Layer Storage — OverlayFS


How does Docker implement copy-on-write layer storage using OverlayFS?Which structs manage the layer graph and what syscalls are made whena new container layer is mounted?
BehaviorWithout CogniRepoClaude explains OverlayFS conceptually. Rarely traces to daemon/graphdriver/overlay2/.With CogniRepocontext_pack("overlay2") returns driver implementation. Syscall path traced.MetricWas mount syscall with lowerdir/upperdir/workdir mentioned?
[MO-4] Multi-language Gap Test ⚠️ CRITICAL


In the Docker daemon, the gRPC server that receives containerd events —trace its registration and the handler that processes TaskExit events.
BehaviorWithout CogniRepoClaude reads Go code.With CogniRepoThis tests whether CogniRepo's Go AST parsing works. If it returns empty or falls back to grep — document the gap in COMPATIBILITY.md.MetricDid CogniRepo return structured Go symbols or raw text?
[MO-5] Image Build Cache Invalidation


How does Docker decide when to invalidate the build cache for a RUN instruction?What factors trigger a cache miss and where is this logic implemented?
BehaviorWithout CogniRepoClaude explains cache invalidation rules. Rarely traces to builder/dockerfile/dispatchers.go.With CogniReposemantic_search("build cache invalidation RUN") returns exact dispatcher logic.MetricWas dispatchers.go or probeCache cited?
REPO 6 — kubernetes/kubernetes (🔴 Extreme / Scale + Complexity)
Goal: Flagship stress test. Token reduction at 2M+ LOC scale.
[K8-1] Pod Scheduling Decision


When a pod is created, trace the full scheduling decision — from the API serverreceiving the pod spec to the scheduler selecting a node. Which components,queues, and scoring plugins are involved?
BehaviorWithout CogniRepoClaude reads from training. K8s scheduler is well-known but tracing exact plugin framework requires reading pkg/scheduler/. Extremely token-heavy.With CogniRepocall_graph_traverse("Schedule") → SchedulingQueue → Framework.RunFilterPlugins. Massive token savings.MetricToken savings expected: 70-80%. Was plugin framework architecture correctly traced?
[K8-2] Controller Reconciliation Loop


Explain the reconciliation loop pattern in Kubernetes controllers.Using the Deployment controller as the example, trace from`DeploymentController.syncDeployment` to how it decides to create/delete ReplicaSets.
BehaviorWithout CogniRepoClaude knows the pattern. Rarely traces syncDeployment → rolloutRolling → scaleUpNewReplicaSet call chain.With CogniRepoFull call chain with file attribution.MetricWere intermediate functions rolloutRolling and scaleUpNewReplicaSet named?
[K8-3] etcd Watch Mechanism


How does Kubernetes watch etcd for changes? Trace from a client calling`kubectl get pods --watch` through the API server to the etcd watch stream.What are the buffering and reconnection semantics?
BehaviorWithout CogniRepoClaude knows watches conceptually. Buffer semantics (RingGrowing) almost never cited.With CogniReposemantic_search("etcd watch buffer reconnect") surfaces RingGrowing and Cacher watcher.MetricWas RingGrowing or watch buffering mechanism cited? (Very high LLM miss rate.)
[K8-4] Admission Controller Chain


When a pod spec hits the API server, what is the exact order of admissioncontrollers that run? How does a webhook admission controller integrateinto this chain? Show the registration and invocation code.
BehaviorWithout CogniRepoClaude lists common admission controllers. Chain ordering and webhook integration point rarely traced to source.With CogniRepocall_graph_traverse("admitPod") returns chain composition in plugin/pkg/admission/.MetricWas webhook's place in chain (after built-ins) correctly attributed to source?
[K8-5] CRD — Custom Resource to API Endpoint


When I apply a CRD to Kubernetes, how does the API server dynamically registerthe new REST endpoints? Trace the path from CRD creation to a working`kubectl get myresource` call.
BehaviorWithout CogniRepoClaude knows CRDs. Dynamic API registration via apiextensions-apiserver rarely traced.With CogniReposemantic_search("CRD dynamic API registration") + symbol_lookup("CustomResourceDefinitionHandler").MetricWas apiextensions-apiserver and DynamicNegotiatedSerializer mentioned?
CURSOR-SPECIFIC PROBES (.cursor/rules/cognirepo.mdc active)
Cursor reads .cursor/rules/*.mdc files. These 2 prompts test if Cursor routes through CogniRepo.
[CU-1] Cursor Rule Routing Validation


[In Cursor chat, on the fastapi repo]How does FastAPI handle validation errors from Pydantic? Show me theexact error response shape and which file constructs it.
BehaviorWithout cognirepo.mdcCursor reads files directly using its own indexer.With cognirepo.mdcCursor should call symbol_lookup("RequestValidationError") via MCP before reading files. Check Cursor's tool calls in the panel.MetricDid Cursor's tool call log show a CogniRepo MCP call? Yes/No.
[CU-2] Cursor Multi-file Refactor


[In Cursor, on the Flask repo]Refactor Flask's session interface so it supports pluggable serializers.Show me all files that need to change and generate the diff.
BehaviorWithout CogniRepoCursor reads session-related files from its own index.With CogniRepocall_graph_traverse("SessionInterface") gives Cursor the exact blast radius before it writes code. Fewer wrong edits.MetricDid Cursor edit the right files on first pass? Compare edit accuracy.
COPILOT-SPECIFIC PROBES (.github/copilot-instructions.md active)
Copilot lacks native MCP support. These test the directive file fallback approach.
[CP-1] Copilot Directive Adherence


[In VS Code with Copilot, on the Celery repo]Explain how Celery's chord primitive works. When does a chord callback fire?
BehaviorWithout copilot-instructions.mdCopilot answers from training + open files.With copilot-instructions.mdCopilot should prepend a note that CogniRepo is available and suggest running cognirepo search "chord callback" in terminal first. This tests if the directive file is being read.MetricDid Copilot reference CogniRepo or suggest the terminal command?
[CP-2] Copilot Compatibility Ceiling Test


[In VS Code with Copilot, on the Kubernetes repo]How does the scheduler framework's Filter phase work? Show implementation.
BehaviorWithout CogniRepoCopilot reads open files. Very limited on a 2M LOC repo.With CogniRepo (terminal-assisted)User runs cognirepo context_pack scheduler_filter in terminal, pastes output into Copilot chat. Manual bridging workflow.MetricQuality delta between raw Copilot vs CogniRepo-assisted Copilot. Documents the gap until Copilot gets native MCP.

