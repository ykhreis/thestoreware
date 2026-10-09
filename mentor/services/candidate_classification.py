from collections import Counter

from mentor.ai_agent_models import (
    KnowledgeChunk,
    KnowledgeSource,
    Term,
    TermAlias,
    TermCandidate,
)


def _normalize(value):
    """Mechanical normalization only; no vocabulary rules."""
    return " ".join((value or "").casefold().split())


def _contains_phrase(text, phrase):
    """Mechanical phrase containment after normalization."""
    normalized_text = _normalize(text)
    normalized_phrase = _normalize(phrase)
    return bool(normalized_phrase and normalized_phrase in normalized_text)


def _source_ids_from_reference(source_reference):
    """
    Resolve KnowledgeSource IDs already recorded on a candidate.

    No business vocabulary is interpreted here. The function only reads the
    existing KnowledgeSource:<id> provenance format written by ingestion.
    """
    source_ids = []

    for part in (source_reference or "").replace("\\n", " ").split():
        if ":" not in part:
            continue

        prefix, value = part.rsplit(":", 1)
        if prefix.casefold().endswith("knowledgesource") and value.isdigit():
            source_ids.append(int(value))

    return list(dict.fromkeys(source_ids))


def _master_knowledge_maps():
    active_terms = list(
        Term.objects.filter(is_active=True)
        .select_related("term_type")
    )

    active_aliases = list(
        TermAlias.objects.filter(is_active=True)
        .select_related("term__term_type")
    )

    term_type_by_text = {}
    canonical_terms = {}

    for term in active_terms:
        normalized = _normalize(term.term)
        if not normalized:
            continue

        canonical_terms[normalized] = term

        if term.term_type_id:
            term_type_by_text[normalized] = term.term_type

    alias_type_by_text = {}
    alias_to_term = {}

    for alias in active_aliases:
        normalized = _normalize(alias.alias)

        if not normalized or not alias.term_id:
            continue

        alias_to_term[normalized] = alias.term

        if alias.term.term_type_id:
            alias_type_by_text[normalized] = alias.term.term_type

    return (
        active_terms,
        active_aliases,
        term_type_by_text,
        alias_type_by_text,
        canonical_terms,
        alias_to_term,
    )


def _contextual_type_for_candidate(
    candidate,
    active_terms,
    active_aliases,
):
    """
    Conservatively suggest a TermType from local sentence-level context.

    A candidate is classified only when:
    - its source provenance resolves to KnowledgeSource records;
    - the candidate occurs in a sentence/line;
    - an existing Master Knowledge Term/Alias whose TermType permits
      contextual classification occurs in that SAME sentence/line;
    - exactly one eligible TermType is supported across those local contexts.

    Ambiguous or unsupported candidates remain unresolved.
    """
    source_ids = _source_ids_from_reference(candidate.source_reference)

    if not source_ids:
        return None, 0

    chunks = list(
        KnowledgeChunk.objects.filter(source_id__in=source_ids)
        .values_list("content", flat=True)
    )

    local_contexts = []

    for content in chunks:
        # Structural splitting only; no vocabulary rules.
        # DOCX extraction already preserves paragraphs/table rows as line breaks.
        for line in (content or "").splitlines():
            if _contains_phrase(line, candidate.term_text):
                local_contexts.append(line)

    if not local_contexts:
        return None, 0

    supported_type_ids = set()
    evidence_count = 0

    for context in local_contexts:
        context_type_ids = set()

        for term in active_terms:
            if (
                term.term_type_id
                and term.term_type.allow_context_classification
                and _normalize(term.term) != _normalize(candidate.term_text)
                and _contains_phrase(context, term.term)
            ):
                context_type_ids.add(term.term_type_id)

        for alias in active_aliases:
            if (
                alias.term_id
                and alias.term.term_type_id
                and alias.term.term_type.allow_context_classification
                and _normalize(alias.alias) != _normalize(candidate.term_text)
                and _contains_phrase(context, alias.alias)
            ):
                context_type_ids.add(alias.term.term_type_id)

        # A local context is useful only when it points to one type.
        if len(context_type_ids) == 1:
            supported_type_ids.update(context_type_ids)
            evidence_count += 1

    # Across all useful local contexts, exactly one type must remain.
    if len(supported_type_ids) != 1:
        return None, evidence_count

    best_type_id = next(iter(supported_type_ids))

    for term in active_terms:
        if (
            term.term_type_id == best_type_id
            and term.term_type.allow_context_classification
        ):
            return term.term_type, evidence_count

    return None, 0

def classify_term_candidates(queryset=None):
    """
    Classify candidates using only the local database.

    Priority:
    1. Exact active Master Knowledge Term match.
    2. Exact active TermAlias match.
    3. Contextual evidence from the candidate's KnowledgeChunks.

    This service:
    - makes no OpenAI/API calls;
    - contains no fixed business vocabulary or stop-word arrays;
    - does not approve or promote candidates;
    - leaves ambiguous/no-evidence candidates unresolved.
    """
    candidates = list(
        (queryset if queryset is not None else TermCandidate.objects.all())
        .select_related("suggested_term_type")
    )

    (
        active_terms,
        active_aliases,
        term_type_by_text,
        alias_type_by_text,
        _canonical_terms,
        _alias_to_term,
    ) = _master_knowledge_maps()

    to_update = []
    matched_existing_term = 0
    matched_alias = 0
    matched_context = 0
    unchanged = 0
    unresolved = 0

    for candidate in candidates:
        normalized = _normalize(candidate.term_text)
        suggested_type = None

        if normalized in term_type_by_text:
            suggested_type = term_type_by_text[normalized]
            matched_existing_term += 1

        elif normalized in alias_type_by_text:
            suggested_type = alias_type_by_text[normalized]
            matched_alias += 1

        else:
            suggested_type, evidence_score = _contextual_type_for_candidate(
                candidate,
                active_terms,
                active_aliases,
            )

            if suggested_type is not None and evidence_score > 0:
                matched_context += 1

        if suggested_type is None:
            unresolved += 1
            continue

        if candidate.suggested_term_type_id == suggested_type.id:
            unchanged += 1
            continue

        candidate.suggested_term_type = suggested_type
        to_update.append(candidate)

    if to_update:
        TermCandidate.objects.bulk_update(
            to_update,
            fields=["suggested_term_type"],
            batch_size=500,
        )

    return {
        "candidates_checked": len(candidates),
        "classified": len(to_update),
        "matched_existing_term": matched_existing_term,
        "matched_alias": matched_alias,
        "matched_context": matched_context,
        "unchanged": unchanged,
        "unresolved": unresolved,
        "openai_used": False,
    }
