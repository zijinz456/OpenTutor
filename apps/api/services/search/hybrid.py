"""Hybrid search with RRF fusion ranking — backward-compatible re-exports.

The implementation has been split into focused modules:
- scoring.py:       query decomposition, tokenization, scoring utilities
- section_merge.py: section grouping and hit deduplication
- strategies.py:    keyword_search, vector_search, tree_search
- fusion.py:        RRF fusion (hybrid_search)
"""

# Re-export public API so existing ``from services.search.hybrid import ...`` still works.
from services.search.fusion import hybrid_search  # noqa: F401
from services.search.scoring import (  # noqa: F401
    RRF_K,
    decompose_search_query,
    rrf_score,
)
from services.search.strategies import (  # noqa: F401
    keyword_search,
    tree_search,
    vector_search,
)
