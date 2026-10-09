import re
from collections import Counter

from django.db import transaction

from mentor.ai_agent_models import (
    KnowledgeSource,
    KnowledgeChunk,
    Term,
    TermAlias,
    TermCandidate,
)


def create_or_update_source(
    name,
    source_type,
    source_reference="",
    organization=None,
    created_by=None,
):
    """
    Create or update a generic KnowledgeSource using the internal database only.
    """
    name = (name or "").strip()
    source_type = (source_type or "").strip()
    source_reference = (source_reference or "").strip()

    if not name:
        raise ValueError("Source name is required.")
    if not source_type:
        raise ValueError("Source type is required.")

    source, created = KnowledgeSource.objects.get_or_create(
        name=name,
        source_reference=source_reference,
        defaults={
            "source_type": source_type,
            "organization": organization,
            "created_by": created_by,
            "processing_status": "PENDING",
            "is_active": True,
        },
    )

    if not created:
        source.source_type = source_type
        source.organization = organization
        if created_by and not source.created_by:
            source.created_by = created_by
        source.is_active = True
        source.save(
            update_fields=[
                "source_type",
                "organization",
                "created_by",
                "is_active",
                "updated_at",
            ]
        )

    return source, created


def _normalize_term_text(value):
    """
    Mechanical normalization only.
    No hard-coded vocabulary, stop-word list, or domain terminology.
    """
    return " ".join((value or "").casefold().split())


def discover_term_candidates(source, chunks):
    """
    Discover previously unknown words from uploaded content and register them
    as TermCandidate records.

    The Master Knowledge database decides what is already known:
    Term and TermAlias are checked dynamically.

    ZERO OpenAI/API usage.
    No fixed vocabulary arrays are used.

    Database operations are performed in bulk so document size does not cause
    one query/insert/update per candidate term.
    """
    text = "\n".join((chunk or "") for chunk in chunks)

    # Generic Unicode word extraction. This is parsing logic, not vocabulary.
    extracted = re.findall(r"\b[^\W\d_][\w-]*\b", text, flags=re.UNICODE)

    if not extracted:
        return {"candidate_terms": 0, "candidate_occurrences": 0}

    counts = Counter(_normalize_term_text(value) for value in extracted)
    counts.pop("", None)

    known_terms = {
        _normalize_term_text(value)
        for value in Term.objects.filter(is_active=True).values_list("term", flat=True)
        if value
    }

    known_aliases = {
        _normalize_term_text(value)
        for value in TermAlias.objects.values_list("alias", flat=True)
        if value
    }

    known = known_terms | known_aliases
    source_reference = f"KnowledgeSource:{source.pk}"

    candidate_counts = {
        normalized_text: occurrence_count
        for normalized_text, occurrence_count in counts.items()
        if normalized_text not in known
    }

    if not candidate_counts:
        return {"candidate_terms": 0, "candidate_occurrences": 0}

    # TermCandidate.term_text is globally unique, so candidate discovery must
    # check globally rather than only within the current source. A term already
    # discovered from another document is reused/skipped instead of inserted
    # again. Its original source_reference is intentionally preserved.
    candidate_texts = list(candidate_counts.keys())
    existing_candidates = list(
        TermCandidate.objects.filter(term_text__in=candidate_texts)
    )
    existing_by_text = {
        _normalize_term_text(candidate.term_text): candidate
        for candidate in existing_candidates
        if candidate.term_text
    }

    to_create = []
    to_update = []

    for normalized_text, occurrence_count in candidate_counts.items():
        candidate = existing_by_text.get(normalized_text)

        if candidate is None:
            to_create.append(
                TermCandidate(
                    term_text=normalized_text,
                    occurrence_count=occurrence_count,
                    found_in_document=True,
                    source_reference=source_reference,
                )
            )
        elif candidate.source_reference == source_reference:
            # Reprocessing the same source: refresh the occurrence count.
            candidate.occurrence_count = occurrence_count
            candidate.found_in_document = True
            to_update.append(candidate)
        else:
            # The term already exists globally from another source.
            # Keep that record/source intact and continue ingestion.
            continue

    if to_create:
        TermCandidate.objects.bulk_create(
            to_create,
            batch_size=500,
            ignore_conflicts=True,
        )

    if to_update:
        TermCandidate.objects.bulk_update(
            to_update,
            fields=["occurrence_count", "found_in_document"],
            batch_size=500,
        )

    return {
        "candidate_terms": len(candidate_counts),
        "candidate_occurrences": sum(candidate_counts.values()),
    }


@transaction.atomic
def store_extracted_content(source, chunks):
    """
    Store extracted content locally.

    No OpenAI call and no external AI call is made.
    """
    if source is None:
        raise ValueError("KnowledgeSource is required.")

    source.processing_status = "PROCESSING"
    source.save(update_fields=["processing_status", "updated_at"])

    stored = 0
    skipped = 0
    seen_indexes = []

    try:
        for index, raw_content in enumerate(chunks, start=1):
            content = (raw_content or "").strip()
            if not content:
                skipped += 1
                continue

            seen_indexes.append(index)

            existing = KnowledgeChunk.objects.filter(
                source=source,
                chunk_index=index,
            ).first()

            if existing:
                if existing.content != content:
                    existing.content = content
                    existing.embedding = None
                    existing.save(
                        update_fields=["content", "embedding", "updated_at"]
                    )
            else:
                KnowledgeChunk.objects.create(
                    source=source,
                    chunk_index=index,
                    content=content,
                )

            stored += 1

        if seen_indexes:
            KnowledgeChunk.objects.filter(source=source).exclude(
                chunk_index__in=seen_indexes
            ).delete()
        else:
            KnowledgeChunk.objects.filter(source=source).delete()

        source.processing_status = "PROCESSED"
        source.save(update_fields=["processing_status", "updated_at"])

    except Exception:
        source.processing_status = "FAILED"
        source.save(update_fields=["processing_status", "updated_at"])
        raise

    return {
        "source_id": source.id,
        "stored": stored,
        "skipped": skipped,
        "status": source.processing_status,
    }


def ingest_file(
    file_path,
    source_name=None,
    organization=None,
    created_by=None,
):
    """
    Generic file ingestion with ZERO OpenAI/API usage.

    Pipeline:
        file
        -> local extraction
        -> KnowledgeSource
        -> KnowledgeChunks
        -> TermCandidate discovery

    Customer/organization is metadata, not hard-coded program logic.
    """
    from pathlib import Path
    from mentor.services.content_extraction import extract_content

    path = Path(file_path)
    extracted = extract_content(path)

    if extracted["chunk_count"] == 0:
        raise ValueError(
            f"No extractable content was found in source: {path.name}"
        )

    final_source_name = (
        (source_name or "").strip()
        or path.stem.replace("_", " ").strip()
    )

    source, created = create_or_update_source(
        name=final_source_name,
        source_type="FILE",
        source_reference=str(path),
        organization=organization,
        created_by=created_by,
    )

    storage_result = store_extracted_content(
        source=source,
        chunks=extracted["chunks"],
    )

    candidate_result = discover_term_candidates(
        source=source,
        chunks=extracted["chunks"],
    )

    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_created": created,
        "source_type": source.source_type,
        "organization": source.organization.name if source.organization else None,
        "processing_status": source.processing_status,
        "extracted_chunks": extracted["chunk_count"],
        "stored_chunks": storage_result["stored"],
        "skipped_chunks": storage_result["skipped"],
        "candidate_terms": candidate_result["candidate_terms"],
        "candidate_occurrences": candidate_result["candidate_occurrences"],
        "openai_used": False,
    }
