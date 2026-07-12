# ReAct Agent Framework

**Production-grade Agent framework with dual implementation** — a handcrafted runtime for transparency and full control, plus a LangGraph-based version for production deployment. 14 modules covering RAG, MCP tool integration, multi-agent orchestration, execution recording/replay, and safety guardrails.

## Overview

This framework provides two complementary implementations of the ReAct (Reasoning + Acting) agent pattern:

| Aspect | Handcrafted Runtime (`src/`) | LangGraph Framework (`experiments/langgraph/`) |
|--------|------------------------------|-----------------------------------------------|
| **Dependencies** | Python stdlib + LLM API only | LangChain + LangGraph |
| **Purpose** | Transparency, learning internals | Production scalability |
| **Control** | Full — every line of the loop | Graph-based orchestration |
| **State management** | Manual | LangGraph's built-in |

## Architecture

### Execution Flow

```
query input
  │
  ├── Direct entry → react_loop()
  │     │
  │     ├── Step 0: Build system prompt (base + role injection + CoT strategy)
  │     ├── Step 1: LLM call → thought/action
  │     ├── Step 2: Tool execution (with permission checking)
  │     ├── Step 3: Observation integration
  │     └── Loop until final answer
  │
  └── Orchestrator entry
        ├── plan() → decompose tasks (with dependency tracking)
        ├── run_worker() → each subtask runs independent react_loop()
        └── synthesize() → merge results
```

### Module Map

```
react_agent/
│
├── react_loop.py         Core ReAct loop (thought → action → observation)
├── llm.py                LLM provider abstraction (multi-provider, configurable)
├── tools/                Tool registry + built-in tools
│   ├── web_search.py     Web search
│   ├── fetch_page.py     Page content extraction
│   ├── execute_python.py Python sandbox execution
│   ├── calculator.py     Arithmetic calculator
│   ├── get_time.py       Time utility
│   ├── summarize.py      Text summarization
│   └── dashboard.py      Web dashboard integration
├── context.py            Context management
├── memory.py             Conversation memory
├── cot.py                Chain-of-Thought strategy injection
├── tot.py                Tree-of-Thought tool integration
├── prompts.py            System prompt construction
├── rag.py                Retrieval-Augmented Generation
│
├── orchestrator.py       Multi-agent task decomposition + synthesis
├── planner.py            Task planning with dependency resolution
├── mcp_client.py         MCP (Model Context Protocol) client for external tools
│
├── eval/                 Evaluation & scoring
│   ├── runner.py         Batch evaluation runner
│   ├── scorer.py         Scoring functions
│   ├── dataset.py        Dataset loading
│   └── report.py         Report generation
│
├── harness/              Execution recording & replay
│   ├── recorder.py       Full trajectory recording
│   ├── replay.py         Step-by-step replay
│   └── sandbox.py        Isolated execution sandbox
│
├── safety/               Safety & permissions
│   ├── permissions.py    Hierarchical permission system (SAFE/NOTIFY/CONFIRM/DENY)
│   ├── human_in_the_loop.py Human oversight callbacks
│   └── trace_watch.py    Execution trace monitoring
│
├── intent/               Task classification
│   └── classifier.py     Intent classification (functional test vs generative)
│
├── dashboard/            Real-time execution visualization
│   └── server.py         Web dashboard
│
└── resilience.py         Error handling & retry logic
```

## Key Features

### Multi-Provider LLM Support

Switch providers via environment variable without code changes:

```bash
export LLM_PROVIDER=deepseek
export LLM_PROVIDER=openai
export LLM_PROVIDER=anthropic
```

Provider configuration in `llm_config.json` with per-provider API keys, base URLs, and model names.

### Permission & Safety System

Four-level permission hierarchy for tool calls:

| Level | Behavior | Use Case |
|-------|----------|----------|
| SAFE | Auto-approve | web_search, calculator |
| NOTIFY | Log + continue | fetch_page (external domains) |
| CONFIRM | Ask user | write_file, execute_python |
| DENY | Block | rm -rf, sensitive paths |

### Execution Recording

Full trajectory capture enables post-hoc analysis:

```python
from react_agent.harness.recorder import current_trajectory

# Record every thought, action, and observation
result = react_loop("Analyze this dataset")
trajectory = current_trajectory()

# Replay later
from react_agent.harness.replay import replay_trajectory
replay_trajectory(trajectory)
```

### RAG & MCP Integration

- **RAG**: Document ingestion, chunking, embedding, and retrieval with configurable vector store
- **MCP Client**: Connect to external MCP servers for tool discovery and invocation

### Multi-Agent Orchestration

Complex tasks are decomposed into subtasks with dependency tracking:

```python
from react_agent.orchestrator import Orchestrator

orc = Orchestrator()
plan = orc.plan("Research and write a report about AI trends")
# → [task_1: search_trends, task_2: analyze, task_3: write_report]
#   task_2 depends on task_1, task_3 depends on task_1 + task_2

results = orc.execute(plan)
```

## LangGraph Version (`experiments/langgraph/`)

A Graph-based implementation using LangChain/LangGraph with the same feature set, suitable for production deployment where framework integration is preferred.

Includes: configurable agent graph, context management, MCP tool integration, RAG pipeline, execution harness, memory management, and multi-agent orchestration.

## Getting Started

```bash
# Install
pip install -e .

# Configure LLM provider
cp .env.example .env
# Edit .env with your API keys

# Run
python -m react_agent "What is the capital of France?"

# Web dashboard
python -m react_agent.dashboard.server
```

## Requirements

- Python 3.10+
- LLM API key (any provider)
- LangChain + LangGraph (for `experiments/langgraph/`, optional)

## Related Projects

- [llm-eval-engine](https://github.com/weihuaguo270-ops/llm-eval-engine) — Production-grade LLM evaluation framework
- [attention-from-scratch](https://github.com/weihuaguo270-ops/attention-from-scratch) — NumPy/PyTorch Transformer attention mechanisms
- [trace-debugger](https://github.com/weihuaguo270-ops/trace-debugger) — Agent execution trace analyzer

## License

MIT
