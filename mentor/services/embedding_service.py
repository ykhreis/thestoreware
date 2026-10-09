"""
OpenAI embedding service — EXPLICIT USE ONLY.

Normal AI-Agent database search, retrieval, answering, and ingestion MUST NOT
import or call this module. It exists only for a future workflow where the user
has explicitly authorized OpenAI usage.

Calling any function in this module requires allow_openai=True.
"""

import os

from openai import OpenAI

from mentor.ai_agent_models import KnowledgeItem, KnowledgeChunk


EMBEDDING_MODEL = "text-embedding-3-small"


def _require_explicit_authorization(allow_openai):
    if allow_openai is not True:
        raise PermissionError(
            "OpenAI usage is disabled for normal AI-Agent operation. "
            "Explicit authorization is required."
        )


# Generic Knowledge embedding configuration.
# This is intentionally separate from the legacy 1536-dimensional
# KnowledgeItem / KnowledgeChunk embedding workflow below.
GENERIC_KNOWLEDGE_EMBEDDING_MODEL = "text-embedding-3-small"
GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS = 384


def generate_generic_knowledge_embedding(text, allow_openai=False):
    """
    Generate one 384-dimensional OpenAI embedding for Generic Knowledge.

    This function does not write anything to the database. It is intended first
    for controlled validation before the Generic Knowledge promotion workflow is
    switched from local ONNX embeddings to OpenAI embeddings.
    """
    _require_explicit_authorization(allow_openai)

    content = (text or "").strip()
    if not content:
        raise ValueError("Text is required for Generic Knowledge embedding.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model=GENERIC_KNOWLEDGE_EMBEDDING_MODEL,
        input=content,
        dimensions=GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS,
    )
    embedding = response.data[0].embedding

    if len(embedding) != GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Unexpected Generic Knowledge embedding dimension: {len(embedding)}. "
            f"Expected {GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS}."
        )

    return embedding


def generate_generic_knowledge_embeddings(texts, allow_openai=False):
    """
    Generate multiple 384-dimensional Generic Knowledge embeddings in one
    OpenAI API request. Returned vectors preserve the same order as input.
    """
    _require_explicit_authorization(allow_openai)

    contents = [(text or "").strip() for text in texts]
    if not contents:
        return []
    if any(not content for content in contents):
        raise ValueError("All texts are required for Generic Knowledge embeddings.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model=GENERIC_KNOWLEDGE_EMBEDDING_MODEL,
        input=contents,
        dimensions=GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS,
    )

    ordered = sorted(response.data, key=lambda item: item.index)
    embeddings = [item.embedding for item in ordered]

    if len(embeddings) != len(contents):
        raise RuntimeError(
            f"Unexpected Generic Knowledge embedding count: {len(embeddings)}. "
            f"Expected {len(contents)}."
        )

    for embedding in embeddings:
        if len(embedding) != GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Unexpected Generic Knowledge embedding dimension: {len(embedding)}. "
                f"Expected {GENERIC_KNOWLEDGE_EMBEDDING_DIMENSIONS}."
            )

    return embeddings


def generate_embedding(text, allow_openai=False):
    _require_explicit_authorization(allow_openai)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    embedding = response.data[0].embedding

    if len(embedding) != 1536:
        raise RuntimeError(
            f"Unexpected embedding dimension: {len(embedding)}. Expected 1536."
        )
    return embedding


def build_embedding_text(item):
    topic_names = list(
        item.topics.filter(is_active=True).values_list("name", flat=True)
    )
    parts = [f"Title: {item.title}", f"Content: {item.content}"]
    if topic_names:
        parts.append("Topics: " + ", ".join(topic_names))
    return "\n".join(parts)


def embed_knowledge_item(item, force=False, allow_openai=False):
    _require_explicit_authorization(allow_openai)
    if item.embedding is not None and not force:
        return False
    item.embedding = generate_embedding(
        build_embedding_text(item),
        allow_openai=True,
    )
    item.save(update_fields=["embedding", "updated_at"])
    return True


def embed_knowledge_chunk(chunk, force=False, allow_openai=False):
    _require_explicit_authorization(allow_openai)
    if chunk.embedding is not None and not force:
        return False
    content = (chunk.content or "").strip()
    if not content:
        return False
    chunk.embedding = generate_embedding(content, allow_openai=True)
    chunk.save(update_fields=["embedding", "updated_at"])
    return True
