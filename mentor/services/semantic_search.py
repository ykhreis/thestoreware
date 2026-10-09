"""
Compatibility wrapper for internal search.

IMPORTANT:
Normal AI-Agent search must have ZERO OpenAI/API usage.
The previous implementation generated an OpenAI query embedding. That behavior
has been removed. Existing stored vector fields may remain in the database for
historical compatibility, but this internal search path does not use them.
"""

from mentor.services.knowledge_search import search_knowledge


def semantic_search(query, limit=5, agent_code=None, source_id=None):
    """
    Backward-compatible search entry point.

    Uses local/database search only. No OpenAI client, embedding API, external
    model, or paid API is called.
    """
    return search_knowledge(
        query=query,
        limit=limit,
        agent_code=agent_code,
        source_id=source_id,
    )
