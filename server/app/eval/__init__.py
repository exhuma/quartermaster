"""In-process catalog evaluation for kit resolution.

Runs a corpus of tasks through the *in-process* resolver (the same embedding
inference path a real client hits) and scores the outcome, so kit authors can
judge their catalog's resolution quality, coverage, and hit rate.

The corpus is portable: one probe is auto-derived per kit from its manifest
(``requires`` = traits that should be inferred, ``excludes`` = traits that must
not), plus a bundled curated language-purity suite. Nothing here mutates the
catalog or per-user memory; it is a read-only measurement.

Layers:
    corpus.py  — case model + generators (pure)
    report.py  — scoring/analysis over resolution records (pure)
    runner.py  — drives cases through the resolver, builds a report
    jobs.py    — in-memory background-job registry for async runs
"""
