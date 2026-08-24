"""FinBit news ingestion pipeline.

Modules, in the order one cycle uses them:

- queries: the nine query definitions and the rotation helper.
- perplexity: the async client for POST /v1/agent.
- extract: the story JSON schema, the prompt rules, parsing and normalization.
- dedupe: pure headline clustering, no database access.
- score: the deterministic importance score.
- ingest: one full cycle, plus the command line entry point.
- scheduler: the APScheduler jobs started by the FastAPI lifespan.

Nothing here is imported eagerly so that importing app.pipeline stays cheap and
free of import cycles. Import the submodule you need directly, for example
``from app.pipeline import ingest``. For the same reason this package defines
no __all__: there is nothing to star-import.
"""
