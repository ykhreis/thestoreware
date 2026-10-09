import re

from mentor.services.knowledge_search import search_knowledge
from mentor.services.generic_knowledge_service import find_generic_knowledge_by_interpretation
from mentor.services.external_ai_service import (
    interpret_internal_question,
    analyze_internal_customer_evidence,
    get_internal_gap_assistance,
)
from mentor.services.professional_brief_service import build_professional_brief


def _source_for_item(item):
    return {
        "kind": "knowledge_item",
        "id": item.id,
        "title": item.title,
        "source_reference": item.source_reference,
        "score": getattr(item, "local_score", 0),
    }


def _source_for_chunk(chunk):
    return {
        "kind": "knowledge_chunk",
        "id": chunk.id,
        "source_id": chunk.source_id,
        "source_name": chunk.source.name,
        "source_reference": chunk.source.source_reference,
        "chunk_index": chunk.chunk_index,
        "score": getattr(chunk, "local_score", 0),
    }


def _clean(text):
    """Normalize AI/database values to safe display text."""
    if text is None:
        return ""
    if isinstance(text, (list, tuple, set)):
        return "\n".join(
            str(value).strip()
            for value in text
            if str(value).strip()
        )
    if isinstance(text, dict):
        return "\n".join(
            f"{key}: {value}"
            for key, value in text.items()
            if str(value).strip()
        )
    return " ".join(str(text).split())


def _text_value(value):
    """Return a safe string when an OpenAI structured field may be text or a list."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "\n".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
    if isinstance(value, dict):
        return "\n".join(
            f"{key}: {item}"
            for key, item in value.items()
            if str(item).strip()
        )
    return str(value).strip()


def _sentences(text):
    """Split stored text into short local statements without external AI."""
    text = _clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s*[•|]\s*|\s+-\s+", text)
    return [part.strip(" -:;") for part in parts if len(part.strip()) >= 25]


def _normalized_words(text):
    return {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+\-/]*", text or "")
        if len(word) > 2
    }



def _is_duplicate(candidate, selected):
    candidate_words = _normalized_words(candidate)
    if not candidate_words:
        return True

    for existing in selected:
        existing_words = _normalized_words(existing)
        if not existing_words:
            continue
        overlap = len(candidate_words & existing_words)
        smaller = min(len(candidate_words), len(existing_words))
        if smaller and overlap / smaller >= 0.72:
            return True
    return False


def _assess_internal_evidence_locally(aspect_evidence):
    """
    Conservative completeness check using only local retrieval metadata.

    Customer/internal document text is NOT sent to OpenAI.  The purpose of this
    step is only to decide which interpreted aspects have local evidence and
    which aspects still need Generic/OpenAI gap assistance.
    """
    assessed = []
    for entry in aspect_evidence or []:
        item_count = int(entry.get("knowledge_items") or 0)
        record_count = int(entry.get("content_records") or 0)
        total = item_count + record_count

        if total == 0:
            status = "NOT_FOUND"
            reason = "No matching Internal / Customer evidence was retrieved."
        elif total == 1:
            status = "PARTIAL"
            reason = "Only one matching Internal / Customer evidence record was retrieved."
        else:
            status = "FOUND"
            reason = "Multiple matching Internal / Customer evidence records were retrieved."

        assessed.append({
            "aspect": entry.get("aspect", ""),
            "status": status,
            "reason": reason,
            "missing_information": "" if status == "FOUND" else entry.get("aspect", ""),
        })

    if not assessed:
        overall = "NOT_FOUND"
    elif any(x["status"] == "NOT_FOUND" for x in assessed):
        overall = "PARTIAL"
    elif any(x["status"] == "PARTIAL" for x in assessed):
        overall = "PARTIAL"
    else:
        overall = "FOUND"

    return {"aspects": assessed, "overall_status": overall}


def _build_internal_answer(question, items, chunks, progress_callback=None):
    """
    Build a grounded investigative brief locally.

    Directly retrieved evidence remains important, but related evidence returned
    by knowledge_search is also allowed to contribute. Selection is based on a
    combination of retrieval relevance, question relevance and complementary
    information rather than requiring every useful statement to repeat the
    literal question words.

    No OpenAI/API call is made.
    """
    if progress_callback:
        progress_callback(80, "Consolidating facts from retrieved internal evidence")

    evidence_records = []

    # Preserve the retrieval score and source order supplied by knowledge_search.
    for item_position, item in enumerate(items):
        for sentence_position, sentence in enumerate(_sentences(item.content)):
            evidence_records.append({
                "sentence": sentence,
                "retrieval_score": float(getattr(item, "local_score", 0) or 0),
                "source_order": item_position,
                "sentence_order": sentence_position,
                "kind": "item",
            })

    for chunk_position, chunk in enumerate(chunks):
        for sentence_position, sentence in enumerate(_sentences(chunk.content)):
            evidence_records.append({
                "sentence": sentence,
                "retrieval_score": float(getattr(chunk, "local_score", 0) or 0),
                "source_order": chunk_position,
                "sentence_order": sentence_position,
                "kind": "chunk",
            })

    if not evidence_records:
        return (
            "Relevant internal information was found, but AI-Agent could not "
            "produce a grounded brief from the stored text."
        )

    question_words = _normalized_words(question)

    # Determine which question words actually occur in the retrieved evidence.
    present_words = set()
    for word in question_words:
        if any(word in _normalized_words(record["sentence"]) for record in evidence_records):
            present_words.add(word)

    ranked = []
    for position, record in enumerate(evidence_records):
        sentence = record["sentence"]
        sentence_words = _normalized_words(sentence)
        query_hits = len(sentence_words & present_words)
        information_density = min(len(sentence_words), 100)

        # Retrieval relevance is now allowed to carry related investigative
        # evidence even when the sentence does not repeat the literal question.
        # Direct question matches still receive a strong bonus.
        score = (
            record["retrieval_score"] * 10000
            + query_hits * 1000
            + information_density
        )

        ranked.append(
            (
                score,
                record["retrieval_score"],
                query_hits,
                -position,
                sentence,
            )
        )

    ranked.sort(reverse=True)

    selected = []

    # Pass 1: preserve the strongest direct evidence.
    for _, _, query_hits, _, sentence in ranked:
        if present_words and query_hits <= 0:
            continue
        if not _is_duplicate(sentence, selected):
            selected.append(sentence)
        if len(selected) >= 4:
            break

    # Pass 2: investigate complementary related evidence. These statements were
    # already admitted by the local DB retrieval layer, so they may add grounded
    # facts even without repeating the exact wording of the question.
    for _, retrieval_score, _, _, sentence in ranked:
        if retrieval_score <= 0:
            continue
        if not _is_duplicate(sentence, selected):
            selected.append(sentence)
        if len(selected) >= 24:
            break

    if not selected:
        return (
            "Relevant internal information was found, but AI-Agent could not "
            "produce a grounded brief from the stored text."
        )

    if progress_callback:
        progress_callback(90, "Building grounded professional brief")

    return build_professional_brief(
        question=question,
        evidence=selected,
    )


def _internal_interpretation_needed(question, results):
    """
    Generic confidence/complexity gate for Internal Knowledge.

    No business vocabulary is hard-coded. OpenAI is used only when:
    - local retrieval found no evidence, or
    - the request is sufficiently complex/multi-part by generic word count.

    Only the user's question is sent to OpenAI; internal/customer content is not.
    """
    items = (results or {}).get("items", [])
    chunks = (results or {}).get("chunks", [])

    if not items and not chunks:
        return True

    word_count = len(re.findall(r"\w+", question or "", flags=re.UNICODE))
    return word_count >= 18


def _interpreted_internal_query(interpretation):
    """
    Convert structured question meaning into a local DB retrieval query.
    This contains no external factual answer.
    """
    parts = [
        (interpretation or {}).get("canonical_concept"),
        (interpretation or {}).get("knowledge_aspect"),
        (interpretation or {}).get("intent"),
    ]
    return " ".join(
        str(part).strip()
        for part in parts
        if str(part or "").strip()
    )


def analyze_question(question, limit=5, source_id=None, source_ids=None, organization_id=None, progress_callback=None):
    """
    INTERNAL AI-AGENT HYBRID MODE.

    The answer remains grounded only in Internal / Customer Knowledge.

    Workflow:
      question -> OpenAI interpretation -> Internal DB aspect investigation
      -> OpenAI analysis of selected customer evidence -> Generic Knowledge for gaps
      -> optional OpenAI external gap assistance -> final answer with customer facts
      and external assistance clearly separated.

    OpenAI interpretation receives the user's question.
    Selected retrieved customer evidence is sent to OpenAI for customer-specific analysis.
    The supplied evidence remains the factual boundary for the customer section.
    External gap assistance is advisory and must never be represented as customer fact.
    """
    def emit(percent, stage):
        if progress_callback:
            progress_callback(percent, stage)

    question = (question or "").strip()
    source_ids = [int(value) for value in (source_ids or ([source_id] if source_id else []))]
    if not question:
        raise ValueError("Question is required.")

    emit(5, "Question received")
    emit(12, f"Organization scope confirmed: {organization_id}")
    emit(
        20,
        "Document scope confirmed"
        if source_ids
        else "Document scope confirmed: all organization documents",
    )

    # Internal Knowledge now follows the same high-level pattern as Generic Knowledge:
    # OpenAI first interprets the question, then AI-Agent investigates only the
    # selected Internal/Customer database for factual evidence.
    emit(25, "Interpreting Internal Knowledge question with OpenAI")
    interpretation = interpret_internal_question(question)
    openai_interpretation_used = True
    interpretation_source = "OPENAI"

    emit(
        35,
        "OpenAI interpretation completed: "
        f"{interpretation.get('canonical_concept', '')} | "
        f"{interpretation.get('knowledge_aspect', '')}",
    )

    # Preserve an original-question retrieval pass as complementary evidence.
    investigation_limit = max(12, limit * 3)

    results = search_knowledge(
        query=question,
        limit=investigation_limit,
        source_ids=source_ids or None,
        organization_id=organization_id,
        progress_callback=None,
        investigation=True,
    )

    aspect_evidence = []
    requested_aspects = interpretation.get("requested_aspects") or []
    emit(
        45,
        f"Investigating {len(requested_aspects)} requested aspect(s) in Internal Knowledge",
    )

    if requested_aspects:

        merged_items = []
        merged_chunks = []
        seen_item_ids = set()
        seen_chunk_ids = set()
        aspect_evidence = []

        for aspect in requested_aspects:
            aspect_query = " ".join(
                part for part in [
                    interpretation.get("canonical_concept", ""),
                    aspect,
                ] if part
            ).strip()

            aspect_results = search_knowledge(
                query=aspect_query,
                limit=investigation_limit,
                source_ids=source_ids or None,
                organization_id=organization_id,
                progress_callback=None,
                investigation=True,
            )

            aspect_items = aspect_results.get("items", [])
            aspect_chunks = aspect_results.get("chunks", [])

            aspect_evidence.append({
                "aspect": aspect,
                "knowledge_items": len(aspect_items),
                "content_records": len(aspect_chunks),
                "found": bool(aspect_items or aspect_chunks),
                "evidence": (
                    [_clean(item.content) for item in aspect_items[:8]]
                    + [_clean(chunk.content) for chunk in aspect_chunks[:12]]
                ),
            })

            for item in aspect_items:
                item_id = getattr(item, "pk", None) or id(item)
                if item_id not in seen_item_ids:
                    seen_item_ids.add(item_id)
                    merged_items.append(item)

            for chunk in aspect_chunks:
                chunk_id = getattr(chunk, "pk", None) or id(chunk)
                if chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk_id)
                    merged_chunks.append(chunk)

        # Preserve original local evidence as well; interpretation expands retrieval,
        # it never discards evidence already found locally.
        for item in results.get("items", []):
            item_id = getattr(item, "pk", None) or id(item)
            if item_id not in seen_item_ids:
                seen_item_ids.add(item_id)
                merged_items.append(item)

        for chunk in results.get("chunks", []):
            chunk_id = getattr(chunk, "pk", None) or id(chunk)
            if chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk_id)
                merged_chunks.append(chunk)

        if merged_items or merged_chunks:
            results = {
                **results,
                "items": merged_items,
                "chunks": merged_chunks,
            }

    items = results.get("items", [])
    chunks = results.get("chunks", [])

    emit(70, "Analyzing retrieved customer evidence with OpenAI")
    customer_evidence_analysis = analyze_internal_customer_evidence(
        question=question,
        interpretation=interpretation,
        aspect_evidence=aspect_evidence,
    )
    evidence_assessment = {
        "aspects": customer_evidence_analysis.get("aspects", []),
        "overall_status": customer_evidence_analysis.get("overall_status", "PARTIAL"),
    }

    gap_count = sum(
        1 for entry in evidence_assessment.get("aspects", [])
        if entry.get("status") in {"PARTIAL", "NOT_FOUND"}
    )

    # Internal / Customer Knowledge stops here by default.
    # Generic Knowledge and OpenAI external knowledge are optional follow-up assistance
    # and are never searched automatically from an Internal question.
    external_assistance = {
        "answer": "",
        "model": None,
        "source_type": "NONE",
        "openai_used": False,
        "gap_aspects": [],
    }
    generic_knowledge_used = False
    generic_knowledge_matches = []

    if gap_count:
        emit(76, f"{gap_count} Internal Knowledge gap(s) identified; additional assistance is optional")
    else:
        emit(76, "Customer evidence covers the requested aspects; additional assistance is optional")

    emit(90, "Internal customer analysis and recommendation completed; no Generic/OpenAI external lookup performed")

    common_trace = {
        "analysis_model": (
            (interpretation or {}).get("model")
            if openai_interpretation_used
            else None
        ),
        "openai_used": openai_interpretation_used,
        "openai_usage_type": (
            "QUESTION_INTERPRETATION + CUSTOMER_EVIDENCE_ANALYSIS"
            if openai_interpretation_used
            else "CUSTOMER_EVIDENCE_ANALYSIS"
        ),
        "interpretation_source": interpretation_source,
        "interpretation": interpretation,
        "requested_aspects": (interpretation or {}).get("requested_aspects", []),
        "aspect_evidence": aspect_evidence,
        "openai_interpretation_used": openai_interpretation_used,
        "openai_customer_evidence_analysis_used": bool(customer_evidence_analysis.get("openai_used")),
        "openai_customer_evidence_analysis_model": customer_evidence_analysis.get("model"),
        "openai_customer_evidence_characters_sent": customer_evidence_analysis.get("evidence_characters_sent", 0),
        "openai_knowledge_used": bool(external_assistance.get("openai_used")),
        "openai_external_lookup_performed": bool(external_assistance.get("openai_used")),
        "answer_information_source": (
            "INTERNAL_DATABASE + GENERIC_KNOWLEDGE + OPENAI"
            if generic_knowledge_used and external_assistance.get("openai_used")
            else "INTERNAL_DATABASE + GENERIC_KNOWLEDGE"
            if generic_knowledge_used
            else "INTERNAL_DATABASE + OPENAI"
            if external_assistance.get("openai_used")
            else "INTERNAL_DATABASE"
        ),
        "evidence_assessment": evidence_assessment,
        "missing_information_identified": bool(gap_count),
        "generic_knowledge_used": generic_knowledge_used,
        "generic_knowledge_matches": generic_knowledge_matches,
        "external_assistance": external_assistance,
        "database_searched": True,
        "recommended_approach": _text_value(customer_evidence_analysis.get("recommended_approach")),
    }

    if not items and not chunks:
        return {
            "answer": (
                "I could not find relevant information in the AI-Agent "
                "internal knowledge base. "
                + (
                    "OpenAI was used only to interpret the question; it was not "
                    "used to provide answer information. "
                    if openai_interpretation_used
                    else "OpenAI was not used. "
                )
                + "If external research is required, it must be requested explicitly."
            ),
            "sources": [],
            "retrieved_items": 0,
            "retrieved_chunks": 0,
            "database_match_found": False,
            **common_trace,
        }

    emit(90, "Using OpenAI customer-evidence analysis as the Internal answer")
    internal_answer = _text_value(customer_evidence_analysis.get("answer"))
    recommended_approach = _text_value(customer_evidence_analysis.get("recommended_approach"))

    answer = (
        "CUSTOMER / INTERNAL INFORMATION\n"
        + internal_answer
    )

    emit(96, "Preparing Internal Knowledge traceability and Pending review")
    sources = (
        [_source_for_item(item) for item in items]
        + [_source_for_chunk(chunk) for chunk in chunks]
    )

    return {
        "answer": answer,
        "sources": sources,
        "retrieved_items": len(items),
        "retrieved_chunks": len(chunks),
        "database_match_found": True,
        **common_trace,
    }

