from django.db.models import Q
from django.db.models import F, Count
from pgvector.django import CosineDistance
from difflib import SequenceMatcher
import re
from time import perf_counter

from mentor.ai_agent_models import GenericKnowledge, GenericKnowledgeItem, GenericKnowledgeCandidate
from mentor.services.external_ai_service import (
    ask_external_ai,
    analyze_external_answer,
    interpret_question,
    analyze_knowledge_consolidation,
)


def _normalize_text(value):
    """
    Normalize text for local comparison.
    No OpenAI call is used here.
    """
    return " ".join((value or "").casefold().split())


def _tokens(value):
    """
    Generic tokenization for local lexical comparison.
    No domain vocabulary, synonym list, or OpenAI call is used.
    """
    return re.findall(r"\w+", _normalize_text(value), flags=re.UNICODE)


def _aspect_match_score(aspect, question):
    """
    Compare a stored knowledge aspect with a new question using only
    generic lexical similarity. Returns a score from 0.0 to 1.0.
    """
    aspect_tokens = _tokens(aspect)
    question_tokens = _tokens(question)

    if not aspect_tokens or not question_tokens:
        return 0.0

    best_scores = []
    for aspect_token in aspect_tokens:
        best = max(
            SequenceMatcher(None, aspect_token, question_token).ratio()
            for question_token in question_tokens
        )
        best_scores.append(best)

    return sum(best_scores) / len(best_scores)




def interpret_question_locally(question):
    """
    Try to understand a question from existing Generic Knowledge metadata.

    This is intentionally lightweight:
    - no OpenAI call;
    - no SentenceTransformer / ONNX model;
    - no runtime embedding;
    - no hardcoded product/domain vocabulary.

    It uses the concepts and knowledge aspects already learned and stored
    in GenericKnowledgeItem.

    Returns a local interpretation only when the match is sufficiently
    strong and unambiguous. Otherwise returns None so OpenAI can remain
    the interpretation fallback.
    """

    question = (question or "").strip()

    if not question:
        return None

    normalized_question = _normalize_text(question)

    items = list(
        GenericKnowledgeItem.objects
        .filter(
            is_active=True,
            generic_knowledge__is_active=True,
        )
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
    )

    matches = []

    for item in items:
        concept = (item.concept or "").strip()
        aspect = (
            getattr(item, "knowledge_aspect", "") or ""
        ).strip()

        if not concept or not aspect:
            continue

        normalized_concept = _normalize_text(concept)

        # How strongly does the stored concept occur in / resemble
        # the user's question?
        concept_in_question = (
            normalized_concept
            and normalized_concept in normalized_question
        )

        concept_score = SequenceMatcher(
            None,
            normalized_concept,
            normalized_question,
        ).ratio()

        if concept_in_question:
            concept_score = 1.0

        # Reuse the existing generic aspect comparison.
        aspect_score = _aspect_match_score(
            aspect,
            question,
        )

        # Conservative local interpretation gate.
        #
        # We accept only when:
        # 1. the stored concept is explicitly present in the question
        #    and the requested aspect has a strong relationship; or
        # 2. both concept and aspect lexical evidence are very strong.
        accepted = (
            (
                concept_in_question
                and aspect_score >= 0.72
            )
            or
            (
                concept_score >= 0.88
                and aspect_score >= 0.80
            )
        )

        if not accepted:
            continue

        combined_score = (
            concept_score * 0.55
            + aspect_score * 0.45
        )

        matches.append(
            (
                combined_score,
                concept_score,
                aspect_score,
                item,
            )
        )

    if not matches:
        return None

    matches.sort(
        key=lambda match: (
            match[0],
            match[1],
            match[2],
        ),
        reverse=True,
    )

    best = matches[0]

    # Do not locally interpret an ambiguous question when two different
    # concept/aspect candidates are almost equally strong.
    if len(matches) > 1:
        second = matches[1]

        best_item = best[3]
        second_item = second[3]

        best_key = (
            _normalize_text(best_item.concept),
            _normalize_text(
                getattr(best_item, "knowledge_aspect", "")
            ),
        )

        second_key = (
            _normalize_text(second_item.concept),
            _normalize_text(
                getattr(second_item, "knowledge_aspect", "")
            ),
        )

        if (
            best_key != second_key
            and (best[0] - second[0]) < 0.035
        ):
            return None

    matched_item = best[3]

    return {
        "canonical_concept": matched_item.concept,
        "knowledge_aspect": getattr(
            matched_item,
            "knowledge_aspect",
            "",
        ),
        "interpretation_source": "LOCAL",
        "local_interpretation_confidence": best[0],
        "local_concept_score": best[1],
        "local_aspect_score": best[2],
        "matched_generic_knowledge_id": (
            matched_item.generic_knowledge_id
        ),
    }



def _local_learned_question_match(question):
    """
    Legacy semantic helper disabled in the interactive web-request service.
    The web path must not load the local ONNX model.
    """
    return None


def _local_structured_semantic_match(question):
    """
    Legacy semantic helper disabled in the interactive web-request service.
    The web path must not load the local ONNX model.
    """
    return None


def find_generic_knowledge(question, progress_callback=None):
    """
    Search the reusable Generic Knowledge database first.

    This function never calls OpenAI.
    """
    search_stage_started_at = perf_counter()


    question = (question or "").strip()

    if not question:
        return None

    normalized_question = _normalize_text(question)

    # First preference:
    # an existing active record created from the same question.
    records = GenericKnowledge.objects.filter(
        is_active=True
    ).exclude(
        validation_status="REJECTED"
    )

    for record in records:
        if _normalize_text(record.question) == normalized_question:
            GenericKnowledge.objects.filter(
                pk=record.pk
            ).update(
                usage_count=F("usage_count") + 1
            )

            record.refresh_from_db(fields=["usage_count"])

            return {
                "answer": record.content,
                "source_type": "GENERIC_DATABASE",
                "model": record.model_name,
                "generic_knowledge_id": record.id,
                "usage_count": record.usage_count,
                "openai_used": False,
                "interpretation_source": "LOCAL",
                "database_searched": True,
                "database_match_found": True,
                "knowledge_source": "GENERIC_KNOWLEDGE",
                "answer_information_source": "GENERIC_KNOWLEDGE",
                "openai_interpretation_used": False,
                "openai_knowledge_used": False,
                "openai_external_lookup_performed": False,
            }

    # Second preference:
    # local semantic search across stored Generic Knowledge embeddings.
    # This uses the local Sentence Transformer model only; OpenAI is not called.
    if progress_callback:
        progress_callback(
            18,
            f"Exact/direct local DB checks completed ({perf_counter() - search_stage_started_at:.2f}s)",
        )

    # FAST PRE-INTERPRETATION BOUNDARY:
    # Do not run the expensive local ONNX/pgvector semantic search here.
    # Exact/direct local DB checks above remain available for obvious matches.
    # If those checks are not sufficient, return immediately so
    # get_generic_answer() can use OpenAI to interpret the question first,
    # then search Generic Knowledge using canonical concept + requested aspect.
    if progress_callback:
        progress_callback(
            25,
            "Pre-interpretation semantic search skipped; using OpenAI interpretation",
        )

    return None


def find_generic_knowledge_by_interpretation(interpretation):
    """
    Lightweight interpreted Generic Knowledge search.

    OpenAI has already normalized the request into canonical concept + requested
    aspect before this function is called. This search therefore stays entirely
    inside PostgreSQL/Python and deliberately does NOT load SentenceTransformer,
    ONNX, or generate a runtime query embedding.

    This keeps the Heroku web request memory-safe while preserving conservative
    concept + aspect matching.
    """
    canonical_concept = (
        (interpretation or {}).get("canonical_concept") or ""
    ).strip()
    knowledge_aspect = (
        (interpretation or {}).get("knowledge_aspect") or ""
    ).strip()

    if not canonical_concept or not knowledge_aspect:
        return None

    normalized_concept = _normalize_text(canonical_concept)
    normalized_aspect = _normalize_text(knowledge_aspect)

    # The Generic Knowledge store is currently small. Read only the fields
    # needed for structured matching; no embeddings/model are loaded.
    candidates = list(
        GenericKnowledgeItem.objects
        .filter(
            is_active=True,
            generic_knowledge__is_active=True,
        )
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
    )

    matches = []

    for item in candidates:
        stored_concept = (item.concept or "").strip()
        stored_aspect = (
            getattr(item, "knowledge_aspect", "") or ""
        ).strip()

        if not stored_concept or not stored_aspect:
            continue

        stored_concept_normalized = _normalize_text(stored_concept)
        stored_aspect_normalized = _normalize_text(stored_aspect)

        concept_exact = stored_concept_normalized == normalized_concept
        aspect_exact = stored_aspect_normalized == normalized_aspect

        concept_lexical = SequenceMatcher(
            None,
            stored_concept_normalized,
            normalized_concept,
        ).ratio()
        aspect_lexical = _aspect_match_score(
            stored_aspect,
            knowledge_aspect,
        )

        if concept_exact:
            concept_lexical = 1.0
        if aspect_exact:
            aspect_lexical = 1.0

        # Conservative structured acceptance:
        # - exact concept + reasonably compatible aspect, OR
        # - very strong lexical concept + strong requested-aspect agreement.
        accepted = (
            (concept_exact and aspect_lexical >= 0.62)
            or
            (concept_lexical >= 0.84 and aspect_lexical >= 0.72)
        )

        if not accepted:
            continue

        combined_score = (
            concept_lexical * 0.55
            + aspect_lexical * 0.45
        )

        matches.append((
            combined_score,
            concept_lexical,
            aspect_lexical,
            item,
        ))

    if not matches:
        return None

    matches.sort(
        key=lambda match: (match[0], match[1], match[2]),
        reverse=True,
    )
    best = matches[0]

    # Do not guess when different requested aspects are nearly tied.
    if len(matches) > 1:
        second = matches[1]
        best_aspect = _normalize_text(
            getattr(best[3], "knowledge_aspect", "")
        )
        second_aspect = _normalize_text(
            getattr(second[3], "knowledge_aspect", "")
        )
        if (
            best_aspect
            and second_aspect
            and best_aspect != second_aspect
            and (best[0] - second[0]) < 0.025
        ):
            return None

    matched_item = best[3]
    record = matched_item.generic_knowledge

    GenericKnowledge.objects.filter(pk=record.pk).update(
        usage_count=F("usage_count") + 1
    )
    record.refresh_from_db(fields=["usage_count"])

    return {
        "answer": record.content,
        "source_type": "GENERIC_DATABASE_INTERPRETED_STRUCTURED_MATCH",
        "model": record.model_name,
        "generic_knowledge_id": record.id,
        "usage_count": record.usage_count,
        "openai_used": True,
        "openai_usage_type": "QUESTION_INTERPRETATION_ONLY",
        "interpretation": interpretation,
        "matched_concept": matched_item.concept,
        "matched_aspect": getattr(matched_item, "knowledge_aspect", ""),
        "interpretation_semantic_score": None,
        "concept_semantic_score": best[1],
        "aspect_semantic_score": best[2],
        "interpretation_source": "OPENAI",
        "database_searched": True,
        "database_match_found": True,
        "knowledge_source": "GENERIC_KNOWLEDGE",
        "answer_information_source": "GENERIC_KNOWLEDGE",
        "openai_interpretation_used": True,
        "openai_knowledge_used": False,
        "openai_external_lookup_performed": False,
    }


def find_existing_knowledge_before_storage(analysis_result, answer):
    """
    Final lightweight duplicate check before staging new external knowledge.

    No local semantic model is loaded here. The analyzed canonical concept and
    requested aspect are compared conservatively with existing reusable items.
    """
    canonical_concept = (
        (analysis_result or {}).get("canonical_concept") or ""
    ).strip()
    knowledge_aspect = (
        (analysis_result or {}).get("knowledge_aspect") or ""
    ).strip()

    if not canonical_concept or not knowledge_aspect:
        return None

    normalized_concept = _normalize_text(canonical_concept)
    normalized_aspect = _normalize_text(knowledge_aspect)

    matches = []

    items = (
        GenericKnowledgeItem.objects
        .filter(is_active=True, generic_knowledge__is_active=True)
        .exclude(validation_status="REJECTED")
        .exclude(generic_knowledge__validation_status="REJECTED")
        .select_related("generic_knowledge")
    )

    for item in items:
        stored_concept = (item.concept or "").strip()
        stored_aspect = (
            getattr(item, "knowledge_aspect", "") or ""
        ).strip()

        if not stored_concept or not stored_aspect:
            continue

        concept_exact = _normalize_text(stored_concept) == normalized_concept
        aspect_exact = _normalize_text(stored_aspect) == normalized_aspect

        concept_score = SequenceMatcher(
            None,
            _normalize_text(stored_concept),
            normalized_concept,
        ).ratio()
        aspect_score = _aspect_match_score(
            stored_aspect,
            knowledge_aspect,
        )

        if concept_exact:
            concept_score = 1.0
        if aspect_exact:
            aspect_score = 1.0

        combined_score = concept_score * 0.55 + aspect_score * 0.45

        if (
            (concept_exact and aspect_score >= 0.72)
            or
            (concept_score >= 0.90 and aspect_score >= 0.82)
        ):
            matches.append((
                combined_score,
                concept_score,
                aspect_score,
                item,
            ))

    if not matches:
        return None

    matches.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best = matches[0]

    if len(matches) > 1:
        second = matches[1]
        best_aspect = _normalize_text(
            getattr(best[3], "knowledge_aspect", "")
        )
        second_aspect = _normalize_text(
            getattr(second[3], "knowledge_aspect", "")
        )
        if (
            best_aspect != second_aspect
            and (best[0] - second[0]) < 0.025
        ):
            return None

    return {
        "item": best[3],
        "combined_score": best[0],
        "concept_score": best[1],
        "aspect_score": best[2],
        "description_score": None,
        "content_score": None,
    }


def _generic_knowledge_db_snapshot():
    """
    Lightweight counts used only to report whether this request added
    reusable Generic Knowledge records.
    """
    return {
        "generic_knowledge": GenericKnowledge.objects.count(),
        "generic_knowledge_item": GenericKnowledgeItem.objects.count(),
    }


def _attach_generic_knowledge_db_update(result, before_counts):
    """
    Attach a transparent database-change summary to the result.

    A normal local reuse may increment usage_count on GenericKnowledge, but it
    does not create new knowledge rows. New reusable knowledge is reported only
    when GenericKnowledge and/or GenericKnowledgeItem row counts increase.
    """
    after_counts = _generic_knowledge_db_snapshot()

    gk_added = max(
        0,
        after_counts["generic_knowledge"] - before_counts["generic_knowledge"],
    )
    item_added = max(
        0,
        after_counts["generic_knowledge_item"] - before_counts["generic_knowledge_item"],
    )

    tables = []
    if gk_added:
        tables.append({
            "table": "generic_knowledge",
            "records_added": gk_added,
            "before": before_counts["generic_knowledge"],
            "after": after_counts["generic_knowledge"],
        })
    if item_added:
        tables.append({
            "table": "generic_knowledge_item",
            "records_added": item_added,
            "before": before_counts["generic_knowledge_item"],
            "after": after_counts["generic_knowledge_item"],
        })

    result["knowledge_database_updated"] = bool(tables)
    result["knowledge_database_tables_updated"] = tables
    result["knowledge_database_before"] = before_counts
    result["knowledge_database_after"] = after_counts
    result["knowledge_records_added"] = gk_added + item_added

    if tables:
        result["knowledge_update_message"] = (
            "AI-Agent learned reusable knowledge from this request and added "
            f"{gk_added} Generic Knowledge record(s) and "
            f"{item_added} Generic Knowledge Item record(s) to the local database."
        )
    else:
        result["knowledge_update_message"] = (
            "No new reusable knowledge records were added to the local database "
            "for this request."
        )

    return result

def get_generic_answer(question, user=None, progress_callback=None):
    """
    Generic Knowledge workflow:

    1. Search GenericKnowledge first.
    2. If found, return stored knowledge with zero OpenAI usage.
    3. If not found, explicitly call OpenAI.
    4. Store the OpenAI result for future reuse.
    """

    question = (question or "").strip()
    db_counts_before = _generic_knowledge_db_snapshot()

    def finalize(result):
        return _attach_generic_knowledge_db_update(
            result,
            db_counts_before,
        )

    def report(percent, stage):
        if progress_callback:
            progress_callback(percent, stage)

    report(5, "Question received")

    if not question:
        raise ValueError("Question is required.")

    report(15, "Searching local Generic Knowledge")
    existing = find_generic_knowledge(question, progress_callback=progress_callback)

    if existing:
        report(100, "Answer retrieved from local Generic Knowledge")
        return finalize(existing)

    # Local retrieval was not sufficiently confident.
    # Use OpenAI only to understand the question, then search the DB again.
    report(40, "Local match not confident; interpreting question with OpenAI")
    interpretation = interpret_question(question)
    report(60, "OpenAI question interpretation completed")

    report(70, "Searching Generic Knowledge using interpreted concept and aspect")
    interpreted_existing = find_generic_knowledge_by_interpretation(
        interpretation
    )

    if interpreted_existing:
        report(100, "Answer retrieved from local Generic Knowledge")
        return finalize(interpreted_existing)

    report(78, "No matching Generic Knowledge found after interpretation")

    # The interpreted concept + requested aspect is still not in the DB.
    # Only now ask OpenAI for the actual external knowledge.
    requires_current_verification = bool(
        (interpretation or {}).get("requires_current_verification", False)
    )
    verification_reason = (
        (interpretation or {}).get("verification_reason") or ""
    ).strip()

    if requires_current_verification:
        report(82, "Current verification required; searching live external sources")
    else:
        report(82, "Requesting external knowledge from OpenAI")

    external_result = ask_external_ai(
        question,
        requires_current_verification=requires_current_verification,
        verification_reason=verification_reason,
    )

    if requires_current_verification:
        report(90, "Current external information verified with OpenAI web search")
    else:
        report(90, "External OpenAI knowledge received")

    answer = (external_result.get("answer") or "").strip()
    model_name = (external_result.get("model") or "").strip()

    if not answer:
        raise ValueError("OpenAI returned an empty answer.")

    analysis_result = analyze_external_answer(
        question=question,
        answer=answer,
    )

    report(92, "External knowledge analysis completed")

    canonical_concept = (
        analysis_result.get("canonical_concept") or ""
    ).strip()
    knowledge_aspect = (
        analysis_result.get("knowledge_aspect") or ""
    ).strip()
    canonical_description = (
        analysis_result.get("canonical_description") or ""
    ).strip()

    matched_item = None
    consolidation_match = None

    # Fast exact canonical duplicate check first.
    if canonical_concept:
        normalized_canonical = _normalize_text(canonical_concept)

        for existing_item in (
            GenericKnowledgeItem.objects
            .filter(is_active=True)
            .exclude(validation_status="REJECTED")
            .select_related("generic_knowledge")
        ):
            same_concept = (
                _normalize_text(existing_item.concept) == normalized_canonical
            )
            same_aspect = (
                _normalize_text(getattr(existing_item, "knowledge_aspect", ""))
                == _normalize_text(knowledge_aspect)
            )
            if same_concept and same_aspect:
                matched_item = existing_item
                break

    # If exact wording differs, semantically compare the analyzed external
    # knowledge with existing DB knowledge BEFORE creating another record.
    if matched_item is None:
        report(93, "Checking for existing equivalent Generic Knowledge")
        consolidation_match = find_existing_knowledge_before_storage(
            analysis_result=analysis_result,
            answer=answer,
        )
        if consolidation_match:
            matched_item = consolidation_match["item"]

    if matched_item:
        report(95, "Existing canonical Generic Knowledge match found")
        record = matched_item.generic_knowledge

        GenericKnowledge.objects.filter(
            pk=record.pk
        ).update(
            usage_count=F("usage_count") + 1
        )

        record.refresh_from_db(fields=["usage_count"])

        report(100, "Answer retrieved from existing Generic Knowledge")
        return finalize({
            "answer": record.content,
            "source_type": "GENERIC_DATABASE_CANONICAL_MATCH",
            "model": record.model_name,
            "generic_knowledge_id": record.id,
            "usage_count": record.usage_count,
            "openai_used": True,
            "analysis": analysis_result,
            "canonical_match": canonical_concept,
            "openai_usage_type": "EXTERNAL_LOOKUP_BUT_DATABASE_ANSWER_USED",
            "interpretation_source": "OPENAI",
            "database_searched": True,
            "database_match_found": True,
            "knowledge_source": "GENERIC_KNOWLEDGE",
            "answer_information_source": "GENERIC_KNOWLEDGE",
            "openai_interpretation_used": True,
            "openai_knowledge_used": False,
            "openai_external_lookup_performed": True,
            "current_verification_required": requires_current_verification,
            "current_verification_performed": bool(
                external_result.get("current_verification_performed", False)
            ),
            "verification_reason": verification_reason,
            "storage_duplicate_prevented": True,
            "storage_action": "REUSED_EXISTING_GENERIC_KNOWLEDGE",
            "consolidation_semantic_score": (
                consolidation_match.get("combined_score")
                if consolidation_match else 1.0
            ),
            "consolidation_concept_score": (
                consolidation_match.get("concept_score")
                if consolidation_match else 1.0
            ),
            "consolidation_aspect_score": (
                consolidation_match.get("aspect_score")
                if consolidation_match else 1.0
            ),
        })

    # GATE 1 — Pending Candidate Intelligence.
    #
    # IMPORTANT:
    # Do not use lexical concept/aspect thresholds here. They can hide a true
    # semantic duplicate from OpenAI before OpenAI has a chance to judge it.
    #
    # Pending is a staging/review area and should remain relatively small, so we
    # send a bounded set of recent Pending candidates directly to the semantic
    # consolidation judge. This is generic across products, languages, wording,
    # and future multimodal-derived text; there are no EBS-specific keywords.
    pending_pool = list(
        GenericKnowledgeCandidate.objects
        .filter(status="PENDING")
        .order_by("-created_at")[:25]
    )

    pending_shortlist = [
        {
            "record_id": pending.id,
            "question": pending.question,
            "canonical_concept": pending.canonical_concept,
            "knowledge_aspect": pending.knowledge_aspect,
            "canonical_description": pending.canonical_description,
            "answer": pending.answer,
        }
        for pending in pending_pool
    ]

    candidate_gate = None
    if pending_shortlist:
        report(94, "Analyzing pending candidates with OpenAI semantic consolidation")
        candidate_gate = analyze_knowledge_consolidation(
            candidate_payload={
                "question": question,
                "canonical_concept": canonical_concept,
                "knowledge_aspect": knowledge_aspect,
                "canonical_description": canonical_description,
                "answer": answer,
                "comparison_instruction": (
                    "Judge whether the reusable knowledge claim is already represented "
                    "by a pending candidate. Treat wording, question form, verbosity, "
                    "citations, and answer formatting as secondary. Focus on the actual "
                    "facts/claims, their scope, and whether the proposed knowledge adds "
                    "a materially distinct reusable fact."
                ),
            },
            comparison_records=pending_shortlist,
            comparison_scope="PENDING_GENERIC_KNOWLEDGE_CANDIDATES",
        )

        matched_candidate_id = candidate_gate.get("matched_record_id")
        decision = candidate_gate.get("decision")
        confidence = candidate_gate.get("confidence", 0.0)

        # Persist Gate-1 diagnostics in the returned result when a new candidate
        # is eventually staged. This makes the learning decision observable
        # without changing the database schema.

        # Only a high-confidence semantic DUPLICATE suppresses creation.
        # UPDATE / MERGE / CONFLICT are intentionally NOT auto-collapsed here:
        # they contain potentially useful differences that belong in review.
        if (
            decision == "DUPLICATE"
            and confidence >= 0.80
            and matched_candidate_id
        ):
            duplicate_candidate = GenericKnowledgeCandidate.objects.filter(
                pk=matched_candidate_id,
                status="PENDING",
            ).first()

            if duplicate_candidate is not None:
                report(
                    100,
                    f"Equivalent pending Candidate #{duplicate_candidate.id} already exists; duplicate staging prevented",
                )
                result = {
                    "answer": duplicate_candidate.answer,
                    "source_type": "GENERIC_PENDING_CANDIDATE_REUSED",
                    "model": duplicate_candidate.model_name,
                    "generic_knowledge_id": None,
                    "generic_knowledge_candidate_id": duplicate_candidate.id,
                    "usage_count": 0,
                    "openai_used": True,
                    "openai_usage_type": "CANDIDATE_CONSOLIDATION",
                    "analysis": analysis_result,
                    "interpretation_source": "OPENAI",
                    "database_searched": True,
                    "database_match_found": False,
                    "knowledge_source": "PENDING_GENERIC_KNOWLEDGE_CANDIDATE",
                    "answer_information_source": "PENDING_CANDIDATE",
                    "openai_interpretation_used": True,
                    "openai_knowledge_used": True,
                    "openai_external_lookup_performed": True,
                    "current_verification_required": requires_current_verification,
                    "current_verification_performed": bool(
                        external_result.get("current_verification_performed", False)
                    ),
                    "verification_reason": verification_reason,
                    "storage_duplicate_prevented": True,
                    "storage_action": "REUSED_EXISTING_PENDING_CANDIDATE",
                    "knowledge_candidate_staged": False,
                    "knowledge_candidate_status": duplicate_candidate.status,
                    "candidate_consolidation": candidate_gate,
                    "candidate_consolidation_decision": candidate_gate.get("decision"),
                    "candidate_consolidation_confidence": candidate_gate.get("confidence"),
                    "candidate_consolidation_matched_id": candidate_gate.get("matched_record_id"),
                    "candidate_consolidation_reason": candidate_gate.get("reason"),
                    "knowledge_update_message": (
                        f"Equivalent pending Generic Knowledge Candidate "
                        f"#{duplicate_candidate.id} already exists; no duplicate "
                        f"candidate was created."
                    ),
                }
                result["knowledge_database_updated"] = False
                result["knowledge_database_tables_updated"] = []
                result["knowledge_database_before"] = db_counts_before
                result["knowledge_database_after"] = _generic_knowledge_db_snapshot()
                result["knowledge_records_added"] = 0
                return result

    staging_started_at = perf_counter()

    candidate = GenericKnowledgeCandidate.objects.create(
        question=question,
        canonical_concept=canonical_concept,
        knowledge_aspect=knowledge_aspect,
        canonical_description=canonical_description,
        answer=answer,
        analysis_json=analysis_result or {},
        model_name=model_name,
        source_type="OPENAI",
        status="PENDING",
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )

    report(
        97,
        f"New external knowledge staged as candidate #{candidate.id} "
        f"({perf_counter() - staging_started_at:.2f}s)"
    )

    # Deliberately stop here:
    # - no final GenericKnowledge row is created during this request;
    # - no GenericKnowledgeItem rows are created during this request;
    # - no SentenceTransformer/ONNX model is loaded;
    # - no semantic embeddings are generated.
    #
    # A separate promotion process will validate/de-duplicate the candidate,
    # create the final reusable records, generate embeddings, and mark the
    # candidate COMPLETED.
    report(100, "External knowledge processed and staged for later promotion")

    result = {
        "answer": answer,
        "source_type": "OPENAI_EXTERNAL_STAGED",
        "model": model_name,
        "generic_knowledge_id": None,
        "generic_knowledge_candidate_id": candidate.id,
        "usage_count": 0,
        "openai_used": True,
        "openai_usage_type": "EXTERNAL_KNOWLEDGE",
        "analysis": analysis_result,
        "interpretation_source": "OPENAI",
        "database_searched": True,
        "database_match_found": False,
        "knowledge_source": "OPENAI_EXTERNAL",
        "answer_information_source": "OPENAI",
        "openai_interpretation_used": True,
        "openai_knowledge_used": True,
        "openai_external_lookup_performed": True,
        "current_verification_required": requires_current_verification,
        "current_verification_performed": bool(
            external_result.get("current_verification_performed", False)
        ),
        "verification_reason": verification_reason,
        "storage_duplicate_prevented": False,
        "storage_action": "STAGED_GENERIC_KNOWLEDGE_CANDIDATE",
        "knowledge_candidate_staged": True,
        "knowledge_candidate_status": candidate.status,
        "candidate_consolidation": candidate_gate,
        "candidate_consolidation_decision": (
            candidate_gate.get("decision") if candidate_gate else "NO_PENDING_COMPARISON"
        ),
        "candidate_consolidation_confidence": (
            candidate_gate.get("confidence") if candidate_gate else None
        ),
        "candidate_consolidation_matched_id": (
            candidate_gate.get("matched_record_id") if candidate_gate else None
        ),
        "candidate_consolidation_reason": (
            candidate_gate.get("reason") if candidate_gate else ""
        ),
        "knowledge_update_message": (
            f"AI-Agent learned new external knowledge and staged it as "
            f"Generic Knowledge Candidate #{candidate.id} for later promotion."
        ),
    }

    # Do not call finalize() here because staging intentionally does not add
    # rows to GenericKnowledge/GenericKnowledgeItem. Preserve the before/after
    # final-table snapshot explicitly for the existing UI/source trace.
    result["knowledge_database_updated"] = False
    result["knowledge_database_tables_updated"] = []
    result["knowledge_database_before"] = db_counts_before
    result["knowledge_database_after"] = _generic_knowledge_db_snapshot()
    result["knowledge_records_added"] = 0

    return result

