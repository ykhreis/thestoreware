from django.db import transaction
from django.utils import timezone
from difflib import SequenceMatcher

from mentor.ai_agent_models import (
    GenericKnowledge,
    GenericKnowledgeCandidate,
    GenericKnowledgeItem,
)
from mentor.services.embedding_service import generate_generic_knowledge_embeddings
from mentor.services.external_ai_service import (
    analyze_knowledge_consolidation,
    compose_generic_knowledge_merge,
)


def _normalize_text(value):
    return " ".join((value or "").casefold().split())


def _candidate_items(candidate):
    """
    Build the final GenericKnowledgeItem payloads from the staged candidate.

    The canonical concept/description becomes the primary reusable item.
    Additional structured items come from candidate.analysis_json["items"].
    Items are de-duplicated locally by normalized concept.
    """
    analysis = candidate.analysis_json or {}
    knowledge_aspect = (candidate.knowledge_aspect or "").strip()

    desired = {}

    canonical_concept = (candidate.canonical_concept or "").strip()
    canonical_description = (candidate.canonical_description or "").strip()

    if canonical_concept and canonical_description:
        desired[_normalize_text(canonical_concept)] = {
            "concept": canonical_concept[:255],
            "knowledge_aspect": knowledge_aspect[:255],
            "description": canonical_description,
            "validation_status": "PENDING",
            "is_active": True,
        }

    for item_data in analysis.get("items", []):
        if not isinstance(item_data, dict):
            continue

        concept = (item_data.get("concept") or "").strip()
        description = (item_data.get("description") or "").strip()

        if not concept or not description:
            continue

        item_aspect = (
            item_data.get("knowledge_aspect")
            or knowledge_aspect
            or ""
        ).strip()

        desired[_normalize_text(concept)] = {
            "concept": concept[:255],
            "knowledge_aspect": item_aspect[:255],
            "description": description,
            "validation_status": "PENDING",
            "is_active": True,
        }

    return list(desired.values())


def _find_exact_existing_parent(candidate):
    """
    Conservative final duplicate check before promotion.

    This deliberately avoids semantic/model loading. If the same canonical
    concept + aspect already exists in final Generic Knowledge Items, reuse
    its parent rather than creating another final knowledge record.
    """
    canonical_concept = _normalize_text(candidate.canonical_concept)
    knowledge_aspect = _normalize_text(candidate.knowledge_aspect)

    if not canonical_concept or not knowledge_aspect:
        return None

    items = (
        GenericKnowledgeItem.objects
        .filter(
            is_active=True,
            generic_knowledge__is_active=True,
        )
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
    )

    for item in items:
        if (
            _normalize_text(item.concept) == canonical_concept
            and _normalize_text(item.knowledge_aspect) == knowledge_aspect
        ):
            return item.generic_knowledge

    return None



def _lexical_score(left, right):
    return SequenceMatcher(
        None,
        _normalize_text(left),
        _normalize_text(right),
    ).ratio()


def _final_knowledge_shortlist(candidate, limit=8):
    """
    Cheap local pre-filter for Gate 2. OpenAI receives only the most relevant
    final knowledge records, never the full Generic Knowledge database.
    """
    rows = (
        GenericKnowledgeItem.objects
        .filter(is_active=True, generic_knowledge__is_active=True)
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
    )

    scored = []
    for item in rows:
        concept_score = _lexical_score(item.concept, candidate.canonical_concept)
        aspect_score = _lexical_score(
            item.knowledge_aspect,
            candidate.knowledge_aspect,
        )
        score = concept_score * 0.55 + aspect_score * 0.45
        if concept_score >= 0.40 or aspect_score >= 0.40:
            scored.append((score, item))

    scored.sort(key=lambda value: value[0], reverse=True)

    result = []
    seen_parent_ids = set()
    for _, item in scored:
        parent = item.generic_knowledge
        if parent.id in seen_parent_ids:
            continue
        seen_parent_ids.add(parent.id)
        result.append({
            "record_id": parent.id,
            "title": parent.title,
            "question": parent.question,
            "content": parent.content,
            "item_concept": item.concept,
            "item_knowledge_aspect": item.knowledge_aspect,
            "item_description": item.description,
            "validation_status": parent.validation_status,
        })
        if len(result) >= limit:
            break

    return result


def _candidate_payload_for_consolidation(candidate):
    return {
        "candidate_id": candidate.id,
        "question": candidate.question,
        "canonical_concept": candidate.canonical_concept,
        "knowledge_aspect": candidate.knowledge_aspect,
        "canonical_description": candidate.canonical_description,
        "answer": candidate.answer,
    }

def promote_generic_knowledge_candidate(candidate_id, progress_callback=None, human_override=None):
    def emit(percent, stage):
        if progress_callback:
            progress_callback(int(percent), stage)
    """
    Promote one staged GenericKnowledgeCandidate into the final reusable
    Generic Knowledge store.

    Uses OpenAI embeddings so Candidate promotion does not load the local
    SentenceTransformer/ONNX model into the web process.

    Returns a small result dictionary suitable for command-line/admin logging.
    """
    emit(10, f"Loading Candidate #{candidate_id}")
    candidate = GenericKnowledgeCandidate.objects.get(pk=candidate_id)
    emit(15, f"Validating Candidate #{candidate.id}")

    if candidate.status == "COMPLETED":
        return {
            "candidate_id": candidate.id,
            "status": "COMPLETED",
            "generic_knowledge_id": candidate.promoted_generic_knowledge_id,
            "items_created": (
                candidate.promoted_generic_knowledge.knowledge_items.count()
                if candidate.promoted_generic_knowledge_id
                else 0
            ),
            "message": "Candidate was already completed; no duplicate promotion performed.",
        }

    if candidate.status == "REJECTED":
        raise ValueError(f"Candidate #{candidate.id} is REJECTED and cannot be promoted.")

    if candidate.status == "PROCESSING":
        raise ValueError(
            f"Candidate #{candidate.id} is already PROCESSING. "
            "Reset/review it before retrying."
        )

    if not (candidate.answer or "").strip():
        raise ValueError(f"Candidate #{candidate.id} has no answer to promote.")

    human_override = (human_override or "").strip().upper()
    if human_override not in {"", "KEEP_SEPARATE", "APPROVE_MERGE"}:
        raise ValueError("Unsupported human override.")

    if human_override == "APPROVE_MERGE":
        gate2_review = (candidate.analysis_json or {}).get("gate2_review") or {}
        consolidation = gate2_review.get("semantic_consolidation") or {}
        decision = str(
            gate2_review.get("consolidation_decision")
            or consolidation.get("decision")
            or ""
        ).strip().upper()
        matched_id = (
            consolidation.get("matched_record_id")
            or gate2_review.get("generic_knowledge_id")
        )

        if decision != "MERGE" or not gate2_review.get("review_required"):
            raise ValueError(
                f"Candidate #{candidate.id} is not waiting for an approved Gate 2 MERGE."
            )
        if not matched_id:
            raise ValueError("Gate 2 MERGE has no matched Generic Knowledge target.")

        target = (
            GenericKnowledge.objects
            .filter(pk=matched_id, is_active=True)
            .exclude(validation_status="REJECTED")
            .first()
        )
        if target is None:
            raise ValueError(f"Matched Generic Knowledge #{matched_id} was not found.")

        existing_items = list(
            target.knowledge_items
            .filter(is_active=True)
            .exclude(validation_status="REJECTED")
            .values("concept", "knowledge_aspect", "description")
        )
        existing_payload = {
            "record_id": target.id,
            "title": target.title,
            "question": target.question,
            "content": target.content,
            "items": existing_items,
        }
        candidate_payload = _candidate_payload_for_consolidation(candidate)
        candidate_payload["items"] = _candidate_items(candidate)

        emit(30, f"Composing controlled merge with Generic Knowledge #{target.id}")
        merged = compose_generic_knowledge_merge(existing_payload, candidate_payload)

        # Preserve the approved candidate's canonical concept + aspect as an
        # explicit retrieval representation on the merged Generic Knowledge.
        # The controlled composer may rewrite/summarize terminology for the
        # consolidated knowledge, but future runtime retrieval must still be
        # able to recognize the exact canonical interpretation that was
        # human-approved for this merge.
        candidate_concept = (candidate.canonical_concept or "").strip()
        candidate_aspect = (candidate.knowledge_aspect or "").strip()
        candidate_description = (candidate.canonical_description or "").strip()

        if candidate_concept and candidate_aspect:
            candidate_key = (
                _normalize_text(candidate_concept),
                _normalize_text(candidate_aspect),
            )
            merged_keys = {
                (
                    _normalize_text(item.get("concept")),
                    _normalize_text(item.get("knowledge_aspect")),
                )
                for item in merged["items"]
            }

            if candidate_key not in merged_keys:
                merged["items"].append({
                    "concept": candidate_concept[:255],
                    "knowledge_aspect": candidate_aspect[:255],
                    "description": (
                        candidate_description
                        or (candidate.answer or "").strip()
                        or candidate_concept
                    ),
                })

        embedding_texts = [
            f"{item['concept']} | {item['knowledge_aspect']}"
            for item in merged["items"]
        ]
        emit(55, "Generating embeddings for merged knowledge")
        vectors = generate_generic_knowledge_embeddings(
            embedding_texts,
            allow_openai=True,
        )

        emit(80, "Applying approved merge transaction")
        with transaction.atomic():
            locked_candidate = (
                GenericKnowledgeCandidate.objects
                .select_for_update()
                .get(pk=candidate.id)
            )
            locked_target = (
                GenericKnowledge.objects
                .select_for_update()
                .get(pk=target.id)
            )

            if locked_candidate.status == "COMPLETED":
                return {
                    "candidate_id": locked_candidate.id,
                    "status": "COMPLETED",
                    "generic_knowledge_id": locked_candidate.promoted_generic_knowledge_id,
                    "items_created": 0,
                    "message": "Candidate completed while approved merge was running.",
                }
            if locked_candidate.status != "PENDING":
                raise ValueError(
                    f"Candidate #{locked_candidate.id} is no longer PENDING."
                )

            audit = dict(locked_candidate.analysis_json or {})
            review = dict(audit.get("gate2_review") or {})
            live_consolidation = review.get("semantic_consolidation") or {}
            live_decision = str(
                review.get("consolidation_decision")
                or live_consolidation.get("decision")
                or ""
            ).strip().upper()
            live_matched_id = (
                live_consolidation.get("matched_record_id")
                or review.get("generic_knowledge_id")
            )
            if (
                live_decision != "MERGE"
                or not review.get("review_required")
                or int(live_matched_id or 0) != locked_target.id
            ):
                raise ValueError("Gate 2 MERGE state changed; approval stopped safely.")

            before_snapshot = {
                "id": locked_target.id,
                "title": locked_target.title,
                "question": locked_target.question,
                "content": locked_target.content,
                "items": list(
                    locked_target.knowledge_items
                    .filter(is_active=True)
                    .values("concept", "knowledge_aspect", "description",
                            "validation_status", "is_active")
                ),
            }

            locked_target.title = merged["title"]
            locked_target.content = merged["content"]
            locked_target.save(update_fields=["title", "content"])

            locked_target.knowledge_items.all().delete()
            rows = [
                GenericKnowledgeItem(
                    generic_knowledge=locked_target,
                    concept=item["concept"],
                    knowledge_aspect=item["knowledge_aspect"],
                    description=item["description"],
                    semantic_embedding=vector,
                    embedding_model="text-embedding-3-small",
                    embedding_dimensions=384,
                    validation_status="PENDING",
                    is_active=True,
                )
                for item, vector in zip(merged["items"], vectors)
            ]
            GenericKnowledgeItem.objects.bulk_create(rows)

            review["human_decision"] = "APPROVE_MERGE"
            review["human_result_status"] = "COMPLETED"
            review["human_result_generic_knowledge_id"] = locked_target.id
            review["merge_summary"] = merged.get("merge_summary", "")
            review["merge_model"] = merged.get("model")
            review["trusted_knowledge_before_merge"] = before_snapshot
            review["trusted_knowledge_after_merge"] = {
                "id": locked_target.id,
                "title": locked_target.title,
                "content": locked_target.content,
                "items": merged["items"],
            }
            audit["gate2_review"] = review

            locked_candidate.status = "COMPLETED"
            locked_candidate.promoted_generic_knowledge = locked_target
            locked_candidate.processed_at = timezone.now()
            locked_candidate.error_message = ""
            locked_candidate.analysis_json = audit
            locked_candidate.save(update_fields=[
                "status", "promoted_generic_knowledge", "processed_at",
                "error_message", "analysis_json", "updated_at",
            ])

        emit(100, f"Candidate #{candidate.id} merged into Generic Knowledge #{target.id}")
        return {
            "candidate_id": candidate.id,
            "status": "COMPLETED",
            "generic_knowledge_id": target.id,
            "items_created": len(rows),
            "merged": True,
            "merge_summary": merged.get("merge_summary", ""),
            "message": (
                f"Candidate #{candidate.id} merged into Generic Knowledge #{target.id}."
            ),
        }

    emit(20, "Preparing structured knowledge items")
    desired_items = _candidate_items(candidate)
    if not desired_items:
        raise ValueError(
            f"Candidate #{candidate.id} contains no valid structured knowledge items."
        )

    # Mark the staging row first. This is intentionally separate from the
    # heavier embedding work so the status is visible if processing fails.
    emit(25, f"Marking Candidate #{candidate.id} as PROCESSING")
    GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
        status="PROCESSING",
        error_message="",
    )

    try:
        # Final exact duplicate protection.
        emit(35, "Checking existing Generic Knowledge for duplicates")
        existing_parent = (
            None
            if human_override == "KEEP_SEPARATE"
            else _find_exact_existing_parent(candidate)
        )
        if existing_parent is not None:
            emit(90, f"Existing Generic Knowledge #{existing_parent.id} found; reusing it")
            GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                status="COMPLETED",
                promoted_generic_knowledge=existing_parent,
                processed_at=timezone.now(),
                error_message="",
            )
            emit(100, f"Candidate #{candidate.id} completed using existing Generic Knowledge #{existing_parent.id}")
            return {
                "candidate_id": candidate.id,
                "status": "COMPLETED",
                "generic_knowledge_id": existing_parent.id,
                "items_created": 0,
                "duplicate_reused": True,
                "message": (
                    f"Candidate #{candidate.id} matched existing Generic Knowledge "
                    f"#{existing_parent.id}; no duplicate final records were created."
                ),
            }

        # GATE 2 — Final Knowledge Intelligence.
        # The exact check above is retained as a cheap first protection.
        # If it did not match, shortlist relevant final knowledge locally and
        # ask OpenAI for a semantic consolidation decision.
        emit(40, "Preparing semantic final-knowledge consolidation check")
        final_shortlist = (
            []
            if human_override == "KEEP_SEPARATE"
            else _final_knowledge_shortlist(candidate)
        )

        consolidation = None
        if final_shortlist:
            emit(43, "Analyzing existing Generic Knowledge with OpenAI")
            consolidation = analyze_knowledge_consolidation(
                candidate_payload=_candidate_payload_for_consolidation(candidate),
                comparison_records=final_shortlist,
                comparison_scope="FINAL_GENERIC_KNOWLEDGE_AND_ITEMS",
            )

            decision = consolidation.get("decision")
            confidence = consolidation.get("confidence", 0.0)
            matched_id = consolidation.get("matched_record_id")

            # High-confidence semantic duplicate: safely reuse the existing
            # final parent instead of creating another final record.
            if decision == "DUPLICATE" and confidence >= 0.80 and matched_id:
                semantic_parent = GenericKnowledge.objects.filter(
                    pk=matched_id,
                    is_active=True,
                ).exclude(validation_status="REJECTED").first()

                if semantic_parent is not None:
                    GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                        status="COMPLETED",
                        promoted_generic_knowledge=semantic_parent,
                        processed_at=timezone.now(),
                        error_message="",
                    )
                    emit(
                        100,
                        f"Semantic duplicate reused Generic Knowledge #{semantic_parent.id}",
                    )
                    return {
                        "candidate_id": candidate.id,
                        "status": "COMPLETED",
                        "generic_knowledge_id": semantic_parent.id,
                        "items_created": 0,
                        "duplicate_reused": True,
                        "semantic_consolidation": consolidation,
                        "message": (
                            f"Candidate #{candidate.id} is semantically equivalent to "
                            f"Generic Knowledge #{semantic_parent.id}; no duplicate "
                            f"final records were created."
                        ),
                    }

            # UPDATE/MERGE/CONFLICT must not silently rewrite trusted knowledge.
            # Return the candidate to PENDING so a human can review the proposed
            # relationship before any final DB mutation.
            if decision in {"UPDATE", "MERGE", "CONFLICT"} and confidence >= 0.70:
                review_message = (
                    f"OpenAI consolidation classified Candidate #{candidate.id} as "
                    f"{decision}"
                    + (f" against Generic Knowledge #{matched_id}" if matched_id else "")
                    + f". {consolidation.get('reason') or ''} "
                    + "No final knowledge was changed; human review is required."
                ).strip()

                GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
                    status="PENDING",
                    error_message=review_message,
                )
                emit(100, f"{decision} detected; candidate returned to Pending Review")
                return {
                    "candidate_id": candidate.id,
                    "status": "PENDING",
                    "generic_knowledge_id": matched_id,
                    "items_created": 0,
                    "duplicate_reused": False,
                    "review_required": True,
                    "consolidation_decision": decision,
                    "semantic_consolidation": consolidation,
                    "message": review_message,
                }

        # Generate embeddings through OpenAI BEFORE final DB writes.
        # This avoids loading the local SentenceTransformer/ONNX model into RAM.
        emit(45, "Preparing embedding texts")
        embedding_texts = [
            f"{item['concept']} | {item['knowledge_aspect']}"
            for item in desired_items
        ]

        emit(55, "Generating OpenAI semantic embeddings")
        vectors = generate_generic_knowledge_embeddings(
            embedding_texts,
            allow_openai=True,
        )

        emit(80, "OpenAI semantic embeddings generated")

        # Final parent + children + candidate completion are committed together.
        emit(85, "Starting final database transaction")
        with transaction.atomic():
            locked_candidate = (
                GenericKnowledgeCandidate.objects
                .select_for_update()
                .get(pk=candidate.id)
            )

            if locked_candidate.status == "COMPLETED":
                return {
                    "candidate_id": locked_candidate.id,
                    "status": "COMPLETED",
                    "generic_knowledge_id": locked_candidate.promoted_generic_knowledge_id,
                    "items_created": 0,
                    "message": "Candidate completed while promotion was running.",
                }

            emit(88, "Creating Generic Knowledge record")
            record = GenericKnowledge.objects.create(
                question=locked_candidate.question,
                title=(
                    (locked_candidate.canonical_concept or "").strip()
                    or locked_candidate.question
                )[:255],
                content=locked_candidate.answer,
                source_type=(
                    locked_candidate.source_type
                    if locked_candidate.source_type in {"OPENAI", "USER", "OTHER"}
                    else "OTHER"
                ),
                model_name=locked_candidate.model_name,
                validation_status="PENDING",
                usage_count=1,
                created_by=locked_candidate.created_by,
                is_active=True,
            )

            rows = []
            for item_data, vector in zip(desired_items, vectors):
                rows.append(
                    GenericKnowledgeItem(
                        generic_knowledge=record,
                        concept=item_data["concept"],
                        knowledge_aspect=item_data["knowledge_aspect"],
                        description=item_data["description"],
                        semantic_embedding=vector,
                        embedding_model="text-embedding-3-small",
                        embedding_dimensions=384,
                        validation_status=item_data["validation_status"],
                        is_active=item_data["is_active"],
                    )
                )

            emit(92, f"Creating {len(rows)} Generic Knowledge Item(s)")
            GenericKnowledgeItem.objects.bulk_create(rows)

            emit(96, f"Linking Candidate #{candidate.id} to Generic Knowledge #{record.id}")
            locked_candidate.status = "COMPLETED"
            locked_candidate.promoted_generic_knowledge = record
            locked_candidate.processed_at = timezone.now()
            locked_candidate.error_message = ""
            locked_candidate.save(
                update_fields=[
                    "status",
                    "promoted_generic_knowledge",
                    "processed_at",
                    "error_message",
                    "updated_at",
                ]
            )

        emit(100, f"Candidate #{candidate.id} completed successfully")
        return {
            "candidate_id": candidate.id,
            "status": "COMPLETED",
            "generic_knowledge_id": record.id,
            "items_created": len(rows),
            "duplicate_reused": False,
            "message": (
                f"Candidate #{candidate.id} promoted to Generic Knowledge "
                f"#{record.id} with {len(rows)} Generic Knowledge Item(s)."
            ),
        }

    except Exception as exc:
        GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
            status="FAILED",
            error_message=str(exc),
            processed_at=timezone.now(),
        )
        raise
