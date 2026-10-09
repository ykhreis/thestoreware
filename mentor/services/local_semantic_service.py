from functools import lru_cache

from pgvector.django import CosineDistance
from sentence_transformers import SentenceTransformer

from mentor.ai_agent_models import GenericKnowledgeItem


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Generic confidence thresholds only.
# These are not domain vocabulary and can later be moved to DB/configuration.
SEMANTIC_MATCH_THRESHOLD = 0.72
ASPECT_SEMANTIC_MATCH_THRESHOLD = 0.68


@lru_cache(maxsize=1)
def get_model():
    """
    Load the local multilingual embedding model once per Python process
    using the memory-efficient quantized ONNX runtime.
    No OpenAI API call is used.
    """
    return SentenceTransformer(
        MODEL_NAME,
        backend="onnx",
        model_kwargs={
            "provider": "CPUExecutionProvider",
            "file_name": "onnx/model_quint8_avx2.onnx",
        },
    )


def embed_text(value):
    """
    Return a normalized 384-dimensional local embedding.
    """
    text = (value or "").strip()
    if not text:
        return None

    vector = get_model().encode(
        text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vector.tolist()


def _cosine_similarity_to_vector(left_text, right_vector):
    """
    Compare one text with an already-computed normalized embedding.

    The question embedding is created once in semantic_match_item() and reused
    for every candidate aspect check. This avoids repeatedly encoding the same
    question while preserving the existing semantic thresholds and behavior.

    No OpenAI API call is used.
    """
    left = (left_text or "").strip()

    if not left or right_vector is None:
        return 0.0

    left_vector = get_model().encode(
        left,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return float(left_vector @ right_vector)


def semantic_match_item(question):
    """
    Find the closest active GenericKnowledgeItem using PostgreSQL/pgvector,
    then verify that the stored requested-information aspect is also
    semantically represented in the new question.

    This prevents a strong shared concept from being enough by itself.
    No domain/aspect vocabulary is hard-coded and OpenAI is not called.

    Returns:
        (item, similarity_score) or (None, similarity_score)
    """
    question_text = (question or "").strip()
    if not question_text:
        return None, None

    # Very fast lexical pre-filter before loading/running the local embedding
    # model. If the question has no meaningful overlap with any stored concept
    # or aspect, return immediately and let the higher-level workflow use
    # OpenAI interpretation instead of paying the ONNX/model-startup cost.
    #
    # This is intentionally conservative: any meaningful overlap keeps the
    # existing semantic path unchanged.
    normalized_question = question_text.casefold()
    lexical_candidates = list(
        GenericKnowledgeItem.objects
        .filter(
            is_active=True,
            generic_knowledge__is_active=True,
            semantic_embedding__isnull=False,
        )
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .values_list("concept", "knowledge_aspect")
    )

    has_overlap = False
    for concept, aspect in lexical_candidates:
        concept_text = (concept or "").strip().casefold()
        aspect_text = (aspect or "").strip().casefold()

        if (
            (concept_text and concept_text in normalized_question)
            or (aspect_text and aspect_text in normalized_question)
        ):
            has_overlap = True
            break

        # Keep semantic retrieval available when a significant stored phrase
        # shares words with the question. No domain vocabulary is hard-coded.
        stored_words = {
            word for word in f"{concept_text} {aspect_text}".split()
            if len(word) >= 4
        }
        question_words = {
            word.strip(".,;:!?()[]{}\"'")
            for word in normalized_question.split()
            if len(word.strip(".,;:!?()[]{}\"'")) >= 4
        }
        if stored_words.intersection(question_words):
            has_overlap = True
            break

    if not has_overlap:
        return None, None

    # Only now load/run the embedding model. The semantic behavior below is
    # unchanged for questions with plausible local overlap.
    query_vector = get_model().encode(
        question_text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_vector_db = query_vector.tolist()

    candidates = list(
        GenericKnowledgeItem.objects
        .filter(
            is_active=True,
            generic_knowledge__is_active=True,
            semantic_embedding__isnull=False,
        )
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
        .annotate(
            semantic_distance=CosineDistance(
                "semantic_embedding",
                query_vector_db,
            )
        )
        .order_by("semantic_distance")[:10]
    )

    if not candidates:
        return None, None

    best_rejected_score = None
    eligible_candidates = []
    eligible_aspects = []

    # First apply the cheap pgvector/overall-confidence gates.
    for candidate in candidates:
        if candidate.semantic_distance is None:
            continue

        overall_similarity = 1.0 - float(candidate.semantic_distance)

        if best_rejected_score is None:
            best_rejected_score = overall_similarity

        if overall_similarity < SEMANTIC_MATCH_THRESHOLD:
            continue

        stored_aspect = (
            getattr(candidate, "knowledge_aspect", "") or ""
        ).strip()

        # Older records without an aspect are not accepted by semantic
        # matching; higher-level DB logic can still evaluate them.
        if not stored_aspect:
            continue

        eligible_candidates.append((candidate, overall_similarity))
        eligible_aspects.append(stored_aspect)

    if not eligible_candidates:
        return None, best_rejected_score

    # Encode all candidate aspects in ONE ONNX batch instead of making one
    # model.encode() call per candidate. The question vector is still created
    # only once above, and the existing thresholds/ordering are unchanged.
    aspect_vectors = get_model().encode(
        eligible_aspects,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    for (candidate, overall_similarity), aspect_vector in zip(
        eligible_candidates,
        aspect_vectors,
    ):
        aspect_similarity = float(aspect_vector @ query_vector)

        if aspect_similarity < ASPECT_SEMANTIC_MATCH_THRESHOLD:
            continue

        return candidate, overall_similarity

    return None, best_rejected_score
