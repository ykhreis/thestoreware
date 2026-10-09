import json
import os

from openai import OpenAI


def ask_external_ai(question, requires_current_verification=False, verification_reason=""):
    """
    Explicit external OpenAI request.

    If semantic interpretation determines that the answer depends on information
    that may have changed over time, enable OpenAI web search for current
    verification. Otherwise preserve the existing lower-cost general-knowledge path.
    """

    question = (question or "").strip()

    if not question:
        raise ValueError("Question is required for External AI.")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not configured."
        )

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    requires_current_verification = bool(requires_current_verification)
    verification_reason = (verification_reason or "").strip()

    request_kwargs = {
        "model": model,
        "instructions": (
            "You are the External Knowledge service of AI-Agent. "
            + (
                "The question has been semantically classified as requiring current "
                "verification. Use web search to verify time-sensitive factual claims "
                "before answering. Prefer authoritative primary sources such as the "
                "product vendor, official documentation, regulator, standards body, "
                "or other first-party authority when available. If current information "
                "cannot be verified confidently, say so instead of presenting an "
                "unverified current fact. "
                if requires_current_verification
                else
                "Answer using general knowledge. "
            )
            + "Do not claim that your answer came from the AI-Agent internal knowledge "
              "database. Be clear, concise, and professional."
        ),
        "input": question,
    }

    if requires_current_verification:
        request_kwargs["tools"] = [{"type": "web_search"}]

    response = client.responses.create(**request_kwargs)

    return {
        "answer": response.output_text,
        "model": model,
        "source_type": (
            "OPENAI_EXTERNAL_WEB_VERIFIED"
            if requires_current_verification
            else "OPENAI_EXTERNAL"
        ),
        "current_verification_required": requires_current_verification,
        "current_verification_performed": requires_current_verification,
        "verification_reason": verification_reason,
    }


def interpret_question(question):
    """
    Use OpenAI only to interpret the user's question.

    This function does NOT answer the question or retrieve external knowledge.
    It returns structured meaning for another Generic Knowledge DB search.
    Call it only when local interpretation/retrieval is not confident enough.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is required for OpenAI interpretation.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    interpretation_input = (
        "USER QUESTION:\\n"
        f"{question}\\n\\n"
        "Interpret the question only. Do not answer it and do not provide "
        "external factual knowledge.\\n\\n"
        "Return valid JSON only using this exact structure:\\n"
        "{\\n"
        '  "canonical_concept": "single canonical name of the main subject",\\n'
        '  "knowledge_aspect": "specific information aspect requested about the main subject",\\n'
        '  "intent": "concise description of what the user is asking to do",\\n'
        '  "requires_current_verification": true,\\n'
        '  "verification_reason": "why current external verification is or is not required"\\n'
        "}\\n\\n"
        "Rules:\\n"
        "- Identify the single main subject.\\n"
        "- Normalize different wording, capitalization, abbreviations, and phrasing "
        "to the same canonical concept when they mean the same thing.\\n"
        "- Identify the requested information aspect semantically; do not use a fixed category list.\\n"
        "- Use a concise reusable knowledge_aspect for comparison with stored knowledge.\\n"
        "- intent describes the request, not the answer.\\n"
        "- Decide requires_current_verification SEMANTICALLY from the meaning of the request.\\n"
        "- Set it to true when a correct answer materially depends on information that may have changed over time and therefore should be verified against current external sources.\\n"
        "- Set it to false when stable/general knowledge is sufficient.\\n"
        "- Do not use a fixed keyword/category list; infer the need for verification from the user's actual intent and subject.\\n"
        "- verification_reason must briefly explain the decision without answering the question.\\n"
        "- Do not add facts, recommendations, explanations, or an answer.\\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the question-interpretation service of AI-Agent. "
            "Only understand and normalize the question for database retrieval. "
            "Do not answer the question. Return JSON only."
        ),
        input=interpretation_input,
    )

    raw_output = (response.output_text or "").strip()
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OpenAI question interpretation did not return valid JSON."
        ) from exc

    canonical_concept = str(parsed.get("canonical_concept") or "").strip()
    knowledge_aspect = str(parsed.get("knowledge_aspect") or "").strip()
    intent = str(parsed.get("intent") or "").strip()
    requires_current_verification = parsed.get("requires_current_verification", False)
    if isinstance(requires_current_verification, str):
        requires_current_verification = (
            requires_current_verification.strip().casefold() == "true"
        )
    else:
        requires_current_verification = bool(requires_current_verification)
    verification_reason = str(parsed.get("verification_reason") or "").strip()

    if not canonical_concept:
        raise ValueError("OpenAI question interpretation did not return a canonical concept.")
    if not knowledge_aspect:
        raise ValueError("OpenAI question interpretation did not return a knowledge aspect.")
    if not intent:
        raise ValueError("OpenAI question interpretation did not return an intent.")

    return {
        "canonical_concept": canonical_concept,
        "knowledge_aspect": knowledge_aspect,
        "intent": intent,
        "requires_current_verification": requires_current_verification,
        "verification_reason": verification_reason,
        "model": model,
        "source_type": "OPENAI_QUESTION_INTERPRETATION",
        "openai_used": True,
    }





def analyze_pending_knowledge_pool(candidate_records):
    """
    Analyze a bounded pool of PENDING Generic Knowledge candidates together.

    Returns semantic groups and per-candidate decisions. This function performs
    analysis only; it never changes database state or promotes knowledge.
    """
    candidate_records = candidate_records or []
    if not candidate_records:
        return {
            "groups": [],
            "candidate_reviews": [],
            "model": "",
            "source_type": "OPENAI_PENDING_POOL_CONSOLIDATION",
            "openai_used": False,
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    payload = json.dumps(candidate_records, ensure_ascii=False)

    response = client.responses.create(
        model=model,
        instructions=(
            "You are AI-Agent's pending-knowledge consolidation engine. "
            "Analyze reusable knowledge claims semantically, not by wording. "
            "Do not promote, delete, reject, or modify knowledge. "
            "Return a review proposal only. Return valid JSON only."
        ),
        input=(
            "Analyze these PENDING Generic Knowledge candidates together:\n\n"
            + payload
            + "\n\n"
            "Create semantic knowledge groups and classify relationships using "
            "DUPLICATE, MERGE, UPDATE, CONFLICT, or UNIQUE.\n\n"
            "Important rules:\n"
            "- Compare actual reusable facts/claims, not merely shared product names.\n"
            "- Different wording/languages can express the same knowledge.\n"
            "- DUPLICATE means materially equivalent reusable knowledge.\n"
            "- MERGE means overlapping/complementary knowledge that should become one cleaner reusable record.\n"
            "- UPDATE means newer/corrected/superseding knowledge replaces older knowledge.\n"
            "- CONFLICT means materially incompatible claims that cannot safely coexist without review.\n"
            "- UNIQUE means materially distinct reusable knowledge that should remain separate.\n"
            "- For time-sensitive/version/status knowledge, distinguish stale facts from current facts when the supplied records make that possible.\n"
            "- Do not invent external facts. Judge only the supplied candidate content.\n"
            "- Choose canonical_candidate_id as the best existing candidate to retain as the base when possible.\n"
            "- proposed_* fields should describe the clean consolidated knowledge proposal, but this is only a proposal.\n"
            "- Every supplied candidate_id must appear exactly once in candidate_reviews.\n\n"
            "Return JSON only with exactly this structure:\n"
            "{\n"
            '  "groups": [\n'
            "    {\n"
            '      "group_id": "G1",\n'
            '      "group_title": "short semantic title",\n'
            '      "candidate_ids": [1, 2],\n'
            '      "canonical_candidate_id": 1,\n'
            '      "group_decision": "DUPLICATE|MERGE|UPDATE|CONFLICT|UNIQUE",\n'
            '      "confidence": 0.0,\n'
            '      "reason": "why these candidates belong together",\n'
            '      "proposed_concept": "clean concept",\n'
            '      "proposed_aspect": "clean aspect",\n'
            '      "proposed_description": "clean reusable description",\n'
            '      "recommended_action": "human-review recommendation"\n'
            "    }\n"
            "  ],\n"
            '  "candidate_reviews": [\n'
            "    {\n"
            '      "candidate_id": 1,\n'
            '      "group_id": "G1",\n'
            '      "relationship": "CANONICAL|DUPLICATE|MERGE|UPDATE|CONFLICT|UNIQUE",\n'
            '      "confidence": 0.0,\n'
            '      "reason": "candidate-specific reason"\n'
            "    }\n"
            "  ]\n"
            "}"
        ),
    )

    try:
        parsed = json.loads((response.output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI pending-pool consolidation did not return valid JSON.") from exc

    groups = parsed.get("groups") or []
    reviews = parsed.get("candidate_reviews") or []
    if not isinstance(groups, list) or not isinstance(reviews, list):
        raise ValueError("OpenAI pending-pool consolidation returned an invalid structure.")

    valid_ids = {int(row["candidate_id"]) for row in candidate_records}
    seen_ids = set()
    cleaned_reviews = []

    allowed_relationships = {
        "CANONICAL", "DUPLICATE", "MERGE", "UPDATE", "CONFLICT", "UNIQUE"
    }

    for review in reviews:
        if not isinstance(review, dict):
            continue
        try:
            candidate_id = int(review.get("candidate_id"))
        except (TypeError, ValueError):
            continue
        if candidate_id not in valid_ids or candidate_id in seen_ids:
            continue

        relationship = str(review.get("relationship") or "").strip().upper()
        if relationship not in allowed_relationships:
            relationship = "UNIQUE"

        try:
            confidence = float(review.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        cleaned_reviews.append({
            "candidate_id": candidate_id,
            "group_id": str(review.get("group_id") or "").strip(),
            "relationship": relationship,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(review.get("reason") or "").strip(),
        })
        seen_ids.add(candidate_id)

    # Never silently lose a candidate if the model omitted it.
    for candidate_id in sorted(valid_ids - seen_ids):
        cleaned_reviews.append({
            "candidate_id": candidate_id,
            "group_id": "",
            "relationship": "UNIQUE",
            "confidence": 0.0,
            "reason": "OpenAI did not classify this candidate; manual review required.",
        })

    cleaned_groups = []
    allowed_group_decisions = {"DUPLICATE", "MERGE", "UPDATE", "CONFLICT", "UNIQUE"}

    for group in groups:
        if not isinstance(group, dict):
            continue
        ids = []
        for value in group.get("candidate_ids") or []:
            try:
                cid = int(value)
            except (TypeError, ValueError):
                continue
            if cid in valid_ids and cid not in ids:
                ids.append(cid)
        if not ids:
            continue

        decision = str(group.get("group_decision") or "").strip().upper()
        if decision not in allowed_group_decisions:
            decision = "UNIQUE"

        canonical_id = group.get("canonical_candidate_id")
        try:
            canonical_id = int(canonical_id) if canonical_id is not None else None
        except (TypeError, ValueError):
            canonical_id = None
        if canonical_id not in ids:
            canonical_id = ids[0]

        try:
            confidence = float(group.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        cleaned_groups.append({
            "group_id": str(group.get("group_id") or "").strip(),
            "group_title": str(group.get("group_title") or "").strip(),
            "candidate_ids": ids,
            "canonical_candidate_id": canonical_id,
            "group_decision": decision,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(group.get("reason") or "").strip(),
            "proposed_concept": str(group.get("proposed_concept") or "").strip(),
            "proposed_aspect": str(group.get("proposed_aspect") or "").strip(),
            "proposed_description": str(group.get("proposed_description") or "").strip(),
            "recommended_action": str(group.get("recommended_action") or "").strip(),
        })

    return {
        "groups": cleaned_groups,
        "candidate_reviews": cleaned_reviews,
        "model": model,
        "source_type": "OPENAI_PENDING_POOL_CONSOLIDATION",
        "openai_used": True,
    }


def analyze_knowledge_consolidation(candidate_payload, comparison_records, comparison_scope):
    """
    Semantic knowledge-consolidation judge.

    The caller first performs a small local shortlist. OpenAI then compares only
    that shortlist with the proposed knowledge and classifies the relationship as:
    NEW, DUPLICATE, UPDATE, MERGE, or CONFLICT.

    This function does not write to the database.
    """
    candidate_payload = candidate_payload or {}
    comparison_records = comparison_records or []
    comparison_scope = (comparison_scope or "").strip()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    consolidation_input = (
        "PROPOSED KNOWLEDGE:\n"
        + json.dumps(candidate_payload, ensure_ascii=False)
        + "\n\nCOMPARISON SCOPE:\n"
        + comparison_scope
        + "\n\nRELEVANT EXISTING RECORDS:\n"
        + json.dumps(comparison_records, ensure_ascii=False)
        + "\n\nReturn valid JSON only using this exact structure:\n"
        "{\n"
        '  "decision": "NEW|DUPLICATE|UPDATE|MERGE|CONFLICT",\n'
        '  "matched_record_id": null,\n'
        '  "confidence": 0.0,\n'
        '  "reason": "concise semantic reason",\n'
        '  "recommended_action": "concise safe action"\n'
        "}\n\n"
        "DECISION RULES:\n"
        "- Judge meaning, not wording. Different wording can still be DUPLICATE.\n"
        "- NEW: no supplied record materially represents the same reusable knowledge.\n"
        "- DUPLICATE: the proposed knowledge is materially equivalent to one supplied record and adds no important new fact.\n"
        "- UPDATE: it represents the same knowledge subject/aspect but contains newer, corrected, superseding, or materially changed information.\n"
        "- MERGE: it overlaps an existing record but adds complementary reusable information that should be consolidated rather than stored separately.\n"
        "- CONFLICT: it makes materially incompatible claims and the supplied evidence is insufficient to safely choose one.\n"
        "- Prefer UPDATE over DUPLICATE when freshness/version/status/time-sensitive facts have changed.\n"
        "- Do not treat records as duplicates merely because they share the same broad subject.\n"
        "- matched_record_id must identify the strongest supplied match for DUPLICATE, UPDATE, MERGE, or CONFLICT; otherwise null.\n"
        "- confidence must be between 0 and 1.\n"
        "- Do not invent facts outside the supplied proposed knowledge and comparison records.\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the semantic knowledge-consolidation judge of AI-Agent. "
            "Protect the knowledge base from semantic duplicates, stale replacements, "
            "unsafe merges, and unresolved conflicts. Return JSON only."
        ),
        input=consolidation_input,
    )

    try:
        parsed = json.loads((response.output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OpenAI knowledge consolidation did not return valid JSON."
        ) from exc

    decision = str(parsed.get("decision") or "").strip().upper()
    if decision not in {"NEW", "DUPLICATE", "UPDATE", "MERGE", "CONFLICT"}:
        raise ValueError("OpenAI knowledge consolidation returned an invalid decision.")

    matched_record_id = parsed.get("matched_record_id")
    if matched_record_id in ("", None):
        matched_record_id = None
    else:
        try:
            matched_record_id = int(matched_record_id)
        except (TypeError, ValueError):
            matched_record_id = None

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "decision": decision,
        "matched_record_id": matched_record_id,
        "confidence": confidence,
        "reason": str(parsed.get("reason") or "").strip(),
        "recommended_action": str(parsed.get("recommended_action") or "").strip(),
        "model": model,
        "source_type": "OPENAI_KNOWLEDGE_CONSOLIDATION",
        "openai_used": True,
    }


def compose_generic_knowledge_merge(existing_record, candidate_payload):
    """
    Create a proposed consolidated version of trusted Generic Knowledge plus one
    approved candidate. This function only composes content; it never writes DB state.
    """
    existing_record = existing_record or {}
    candidate_payload = candidate_payload or {}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    merge_input = (
        "EXISTING TRUSTED GENERIC KNOWLEDGE:\n"
        + json.dumps(existing_record, ensure_ascii=False)
        + "\n\nAPPROVED MERGE CANDIDATE:\n"
        + json.dumps(candidate_payload, ensure_ascii=False)
        + "\n\nCreate one clean consolidated reusable knowledge record. "
        "Use ONLY facts supported by these two supplied inputs. Preserve valid existing "
        "knowledge, add complementary candidate knowledge, remove repetition, and do not "
        "invent, externally verify, or silently resolve a genuine conflict.\n\n"
        "Return valid JSON only using exactly this structure:\n"
        "{\n"
        '  "title": "concise canonical title",\n'
        '  "content": "complete consolidated reusable answer",\n'
        '  "items": [\n'
        "    {\n"
        '      "concept": "canonical reusable concept",\n'
        '      "knowledge_aspect": "specific reusable aspect",\n'
        '      "description": "standalone consolidated description"\n'
        "    }\n"
        "  ],\n"
        '  "merge_summary": "concise explanation of what was added or consolidated"\n'
        "}\n\n"
        "STRICT RULES:\n"
        "- Do not add any fact not present in the supplied existing record or candidate.\n"
        "- Do not use web search or outside knowledge.\n"
        "- Do not merely concatenate the two texts; consolidate semantically.\n"
        "- Preserve materially distinct valid information from both inputs.\n"
        "- Remove duplicate wording and redundant claims.\n"
        "- If the supplied inputs materially conflict and cannot safely be reconciled, "
        'return JSON with "merge_blocked": true and explain the conflict in merge_summary.\n'
        "- Otherwise return merge_blocked as false or omit it.\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are AI-Agent's controlled Generic Knowledge merge composer. "
            "You may synthesize only the supplied trusted record and approved candidate. "
            "Do not use external knowledge. Return JSON only."
        ),
        input=merge_input,
    )

    try:
        parsed = json.loads((response.output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI Generic Knowledge merge did not return valid JSON.") from exc

    if bool(parsed.get("merge_blocked")):
        raise ValueError(
            "Controlled merge was blocked: "
            + str(parsed.get("merge_summary") or "the supplied knowledge could not be safely merged.")
        )

    title = str(parsed.get("title") or "").strip()
    content = str(parsed.get("content") or "").strip()
    raw_items = parsed.get("items") or []
    if not title or not content or not isinstance(raw_items, list):
        raise ValueError("OpenAI Generic Knowledge merge returned an invalid structure.")

    items = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        concept = str(item.get("concept") or "").strip()
        aspect = str(item.get("knowledge_aspect") or "").strip()
        description = str(item.get("description") or "").strip()
        key = (" ".join(concept.casefold().split()), " ".join(aspect.casefold().split()))
        if concept and aspect and description and key not in seen:
            seen.add(key)
            items.append({
                "concept": concept[:255],
                "knowledge_aspect": aspect[:255],
                "description": description,
            })

    if not items:
        raise ValueError("Controlled merge produced no reusable knowledge items.")

    return {
        "title": title[:255],
        "content": content,
        "items": items,
        "merge_summary": str(parsed.get("merge_summary") or "").strip(),
        "model": model,
        "source_type": "OPENAI_CONTROLLED_KNOWLEDGE_MERGE",
        "openai_used": True,
    }

def interpret_internal_question(question):
    """
    Use OpenAI to understand an Internal / Customer Knowledge question and
    create a compact professional investigation plan for local database retrieval.

    IMPORTANT:
    - Only the user's question is sent to OpenAI.
    - No customer/internal document content is sent.
    - OpenAI does not answer the question and does not provide customer facts.
    - requested_aspects is dynamic; there is no fixed business vocabulary.
    - The interpretation must identify the underlying professional objective,
      not merely paraphrase words appearing in the question.
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is required for Internal Knowledge interpretation.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    interpretation_input = (
        "USER QUESTION:\n"
        f"{question}\n\n"
        "Your task is to INTERPRET the user's professional objective and create "
        "a comprehensive investigation plan for searching the customer's local "
        "Internal Knowledge documents. Do NOT answer the question. Do NOT provide "
        "external factual knowledge. Do NOT invent or assume customer facts.\n\n"
        "Return valid JSON only using this exact structure:\n"
        "{\n"
        '  "canonical_concept": "normalized main subject being investigated",\n'
        '  "professional_objective": "what the user is ultimately trying to assess, decide, prepare, validate, compare, troubleshoot, plan, or understand",\n'
        '  "requested_aspects": ["investigation aspect 1", "investigation aspect 2"],\n'
        '  "intent": "concise description of the investigation to perform on the customer documents"\n'
        "}\n\n"
        "INVESTIGATION RULES:\n"
        "- First infer the underlying professional objective from the complete meaning "
        "of the question, not only its literal keywords.\n"
        "- requested_aspects must be an INVESTIGATION PLAN: identify the distinct "
        "information dimensions that should be searched in customer/internal documents "
        "to satisfy that professional objective properly.\n"
        "- Include both information explicitly requested and information reasonably "
        "necessary to perform the requested professional assessment or task.\n"
        "- For a broad or complex request, return no more than 10 requested_aspects. "
        "For a simple request, return fewer; never create extra aspects just to reach 10.\n"
        "- Consolidate closely related dimensions into one aspect instead of creating "
        "many narrow sub-aspects.\n"
        "- Each aspect must be a short retrieval phrase, preferably 3-10 words. "
        "Never return a paragraph, sentence-length checklist, or comma-separated catalogue as one aspect.\n"
        "- Each aspect must represent one coherent investigation dimension and be useful "
        "directly as a local database/document retrieval target.\n"
        "- Prioritize the dimensions most important to the professional objective. "
        "Be complete at the investigation-dimension level, not exhaustive at individual-field level.\n"
        "- Derive all aspects dynamically from the question and its professional context. "
        "Do not use or assume a fixed category list.\n"
        "- Do not state what the customer's current environment contains. The local "
        "AI-Agent database will determine that from uploaded documents.\n"
        "- Do not provide recommendations, best practices, answers, or external facts.\n"
        "- Do not infer customer-specific data that is not present in the question.\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the professional investigation-planning service for AI-Agent "
            "Internal / Customer Knowledge. Understand the user's underlying business "
            "or technical objective and produce a compact, prioritized, dynamic set of local "
            "document investigation aspects. Do not answer the question, do not provide "
            "external knowledge, and do not invent customer facts. Return JSON only."
        ),
        input=interpretation_input,
    )

    raw_output = (response.output_text or "").strip()
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OpenAI Internal Knowledge interpretation did not return valid JSON."
        ) from exc

    canonical_concept = str(parsed.get("canonical_concept") or "").strip()
    professional_objective = str(parsed.get("professional_objective") or "").strip()
    intent = str(parsed.get("intent") or "").strip()
    raw_aspects = parsed.get("requested_aspects") or []

    if not isinstance(raw_aspects, list):
        raise ValueError(
            "OpenAI Internal Knowledge interpretation returned invalid requested_aspects."
        )

    requested_aspects = []
    seen = set()
    for aspect in raw_aspects:
        aspect = str(aspect or "").strip()
        key = " ".join(aspect.casefold().split())
        if aspect and key not in seen:
            seen.add(key)
            requested_aspects.append(aspect)
        if len(requested_aspects) >= 10:
            break

    if not canonical_concept:
        raise ValueError(
            "OpenAI Internal Knowledge interpretation did not return a canonical concept."
        )
    if not professional_objective:
        # Backward-safe fallback: intent still carries the interpreted objective.
        professional_objective = intent
    if not requested_aspects:
        raise ValueError(
            "OpenAI Internal Knowledge interpretation did not return requested aspects."
        )
    if not intent:
        raise ValueError(
            "OpenAI Internal Knowledge interpretation did not return an intent."
        )

    return {
        "canonical_concept": canonical_concept,
        "professional_objective": professional_objective,
        "requested_aspects": requested_aspects,
        "knowledge_aspect": "; ".join(requested_aspects),
        "intent": intent,
        "model": model,
        "source_type": "OPENAI_INTERNAL_QUESTION_INTERPRETATION",
        "openai_used": True,
    }

def analyze_external_answer(question, answer):
    """
    Analyze a completed external answer using OpenAI.

    This is a separate paid OpenAI request. It must only be called after
    an explicit Generic Knowledge / OpenAI request has already produced
    the full answer.

    The goal is semantic knowledge extraction, not keyword matching.
    Incidental words must not become knowledge items merely because they
    appear in the answer.
    """

    question = (question or "").strip()
    answer = (answer or "").strip()

    if not question:
        raise ValueError("Question is required for External AI analysis.")

    if not answer:
        raise ValueError("Answer is required for External AI analysis.")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    analysis_input = (
        "ORIGINAL QUESTION:\n"
        f"{question}\n\n"
        "FULL ANSWER TO ANALYZE:\n"
        f"{answer}\n\n"
        "Return valid JSON only using this exact structure:\n"
        "{\n"
        '  "canonical_concept": "single canonical name of the main subject",\n'
        '  "knowledge_aspect": "specific information aspect requested about the main subject",\n'
        '  "canonical_description": "standalone description of the requested knowledge about the main subject",\n'
        '  "items": [\n'
        "    {\n"
        '      "concept": "meaningful reusable concept",\n'
        '      "description": "accurate reusable description supported by the answer"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Extraction rules:\n"
        "- canonical_concept must be the single normalized/canonical main subject of the question.\n"
        "- knowledge_aspect must identify the specific information requested about that subject.\n"
        "- Determine knowledge_aspect semantically from the supplied question and answer; do not rely on a fixed category list.\n"
        "- Use a concise reusable aspect name that distinguishes different kinds of knowledge about the same canonical concept.\n"
        "- canonical_description must describe the requested knowledge accurately and stand on its own.\n"
        "- Different wording, capitalization, articles, abbreviations, or phrasing must not create a different canonical concept when the meaning is the same.\n"
        "- Identify the main concept directly answering the question.\n"
        "- Include important related concepts only when the answer provides "
        "substantive reusable knowledge about them.\n"
        "- Do not extract a word merely because it appears in the answer.\n"
        "- Exclude incidental examples, generic nouns, formatting labels, "
        "and passing references.\n"
        "- Prefer complete canonical concept names over fragments.\n"
        "- Each description must be understandable on its own.\n"
        "- Do not invent information that is not supported by the supplied answer.\n"
        "- Do not return duplicate concepts.\n"
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the semantic knowledge-analysis service of AI-Agent. "
            "Analyze the supplied question and completed answer for reusable "
            "knowledge. Distinguish the actual subject and meaningful related "
            "concepts from incidental words. Return JSON only."
        ),
        input=analysis_input,
    )

    raw_output = (response.output_text or "").strip()

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "OpenAI knowledge analysis did not return valid JSON."
        ) from exc

    canonical_concept = str(parsed.get("canonical_concept") or "").strip()
    knowledge_aspect = str(parsed.get("knowledge_aspect") or "").strip()
    canonical_description = str(parsed.get("canonical_description") or "").strip()

    if not canonical_concept:
        raise ValueError("OpenAI knowledge analysis did not return a canonical concept.")

    if not knowledge_aspect:
        raise ValueError("OpenAI knowledge analysis did not return a knowledge aspect.")

    if not canonical_description:
        raise ValueError("OpenAI knowledge analysis did not return a canonical description.")

    items = parsed.get("items", [])

    if not isinstance(items, list):
        raise ValueError("OpenAI knowledge analysis returned an invalid items structure.")

    cleaned_items = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        concept = str(item.get("concept") or "").strip()
        description = str(item.get("description") or "").strip()

        if not concept or not description:
            continue

        normalized_concept = " ".join(concept.casefold().split())

        if normalized_concept in seen:
            continue

        seen.add(normalized_concept)

        cleaned_items.append(
            {
                "concept": concept,
                "description": description,
            }
        )

    return {
        "canonical_concept": canonical_concept,
        "knowledge_aspect": knowledge_aspect,
        "canonical_description": canonical_description,
        "items": cleaned_items,
        "model": model,
        "source_type": "OPENAI_ANALYSIS",
        "openai_used": True,
    }


def assess_internal_evidence(question, interpretation, aspect_evidence):
    """
    Ask OpenAI to assess completeness of already-retrieved Internal Knowledge evidence.

    Customer/internal evidence is sent only for completeness assessment.
    OpenAI must not invent customer facts. The result classifies each requested
    aspect as FOUND, PARTIAL, or NOT_FOUND and identifies gaps.
    """
    question = (question or "").strip()
    interpretation = interpretation or {}
    aspect_evidence = aspect_evidence or []

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    compact_aspects = []
    for entry in aspect_evidence:
        compact_aspects.append({
            "aspect": str(entry.get("aspect") or "").strip(),
            "evidence": [
                str(value or "").strip()
                for value in (entry.get("evidence") or [])
                if str(value or "").strip()
            ],
        })

    assessment_input = (
        "USER QUESTION:\n" + question + "\n\n"
        "QUESTION INTERPRETATION:\n" + json.dumps(interpretation, ensure_ascii=False) + "\n\n"
        "RETRIEVED INTERNAL/CUSTOMER EVIDENCE BY ASPECT:\n"
        + json.dumps(compact_aspects, ensure_ascii=False) + "\n\n"
        "Assess evidence completeness only. Do not invent customer facts.\n"
        "Return valid JSON only using this structure:\n"
        "{\n"
        '  "aspects": [\n'
        "    {\n"
        '      "aspect": "requested aspect",\n'
        '      "status": "FOUND|PARTIAL|NOT_FOUND",\n'
        '      "reason": "short evidence-grounded reason",\n'
        '      "missing_information": ["specific missing point"]\n'
        "    }\n"
        "  ],\n"
        '  "overall_status": "FOUND|PARTIAL|NOT_FOUND"\n'
        "}\n\n"
        "Rules:\n"
        "- FOUND means the retrieved evidence sufficiently answers that aspect.\n"
        "- PARTIAL means relevant evidence exists but important information is missing.\n"
        "- NOT_FOUND means the supplied evidence does not answer that aspect.\n"
        "- Treat only supplied evidence as customer facts.\n"
        "- Do not add external facts, recommendations, or assumptions.\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the Internal Knowledge evidence-completeness assessor of AI-Agent. "
            "Classify supplied customer evidence without inventing facts. Return JSON only."
        ),
        input=assessment_input,
    )

    try:
        parsed = json.loads((response.output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI Internal evidence assessment did not return valid JSON.") from exc

    aspects = parsed.get("aspects") or []
    if not isinstance(aspects, list):
        aspects = []

    cleaned = []
    for item in aspects:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().upper()
        if status not in {"FOUND", "PARTIAL", "NOT_FOUND"}:
            status = "PARTIAL"
        missing = item.get("missing_information") or []
        if not isinstance(missing, list):
            missing = [str(missing)]
        cleaned.append({
            "aspect": str(item.get("aspect") or "").strip(),
            "status": status,
            "reason": str(item.get("reason") or "").strip(),
            "missing_information": [
                str(value or "").strip() for value in missing if str(value or "").strip()
            ],
        })

    overall_status = str(parsed.get("overall_status") or "").strip().upper()
    if overall_status not in {"FOUND", "PARTIAL", "NOT_FOUND"}:
        statuses = {item["status"] for item in cleaned}
        overall_status = (
            "NOT_FOUND" if statuses == {"NOT_FOUND"}
            else "PARTIAL" if ("PARTIAL" in statuses or "NOT_FOUND" in statuses)
            else "FOUND"
        )

    return {
        "aspects": cleaned,
        "overall_status": overall_status,
        "model": model,
        "source_type": "OPENAI_INTERNAL_EVIDENCE_ASSESSMENT",
        "openai_used": True,
    }



def analyze_internal_customer_evidence(question, interpretation, aspect_evidence):
    """
    Analyze retrieved Internal / Customer evidence with OpenAI.

    The supplied evidence is the factual boundary for customer-specific statements.
    OpenAI may correlate, synthesize and assess the evidence, but must not invent
    customer facts or mix general/external knowledge into the customer analysis.
    """
    question = (question or "").strip()
    interpretation = interpretation or {}
    aspect_evidence = aspect_evidence or []

    if not question:
        raise ValueError("Question is required for Internal customer evidence analysis.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    # Keep the payload controlled: only retrieved evidence, deduplicated and capped.
    compact_aspects = []
    seen_evidence = set()
    total_chars = 0
    max_total_chars = int(os.getenv("INTERNAL_AI_EVIDENCE_MAX_CHARS", "60000"))

    for entry in aspect_evidence:
        evidence_values = []
        for value in (entry.get("evidence") or []):
            value = " ".join(str(value or "").split())
            if not value:
                continue
            key = value.casefold()
            if key in seen_evidence:
                continue
            if total_chars + len(value) > max_total_chars:
                break
            seen_evidence.add(key)
            evidence_values.append(value)
            total_chars += len(value)

        compact_aspects.append({
            "aspect": str(entry.get("aspect") or "").strip(),
            "evidence": evidence_values,
        })
        if total_chars >= max_total_chars:
            break

    analysis_input = (
        "USER QUESTION:\n" + question + "\n\n"
        "QUESTION INTERPRETATION:\n"
        + json.dumps(interpretation, ensure_ascii=False) + "\n\n"
        "RETRIEVED CUSTOMER/INTERNAL EVIDENCE BY INVESTIGATION ASPECT:\n"
        + json.dumps(compact_aspects, ensure_ascii=False) + "\n\n"
        "Analyze the supplied customer evidence as a professional analyst. "
        "Correlate facts across evidence records and answer the user's actual objective, "
        "rather than repeating isolated sentences or questionnaire questions.\n\n"
        "Return valid JSON only using this exact structure:\n"
        "{\n"
        '  "customer_analysis": "professional customer-specific answer based only on supplied evidence",\n'
        '  "recommended_approach": "customer-specific next-step approach derived only from the supplied evidence and identified gaps",\n'
        '  "aspects": [\n'
        "    {\n"
        '      "aspect": "requested investigation aspect",\n'
        '      "status": "FOUND|PARTIAL|NOT_FOUND",\n'
        '      "summary": "concise synthesis of what the evidence establishes",\n'
        '      "missing_information": ["specific information still missing"]\n'
        "    }\n"
        "  ],\n"
        '  "overall_status": "FOUND|PARTIAL|NOT_FOUND"\n'
        "}\n\n"
        "STRICT RULES:\n"
        "- Treat ONLY the supplied evidence as customer facts.\n"
        "- Do not use general knowledge, assumptions, or external facts in customer_analysis.\n"
        "- Synthesize and correlate evidence across records; do not merely copy sentences.\n"
        "- Distinguish actual answers/facts from questions, requests, placeholders, TBDs, and assumptions in source material.\n"
        "- A questionnaire question is NOT evidence that the requested fact is known.\n"
        "- If different evidence conflicts, state the conflict instead of choosing silently.\n"
        "- Organize customer_analysis around the user's professional objective and the meaningful investigation aspects.\n"
        "- Include useful concrete values, versions, modules, quantities, costs, platforms, environments, constraints, or statuses when the evidence supplies them.\n"
        "- FOUND means the supplied evidence materially answers the aspect; PARTIAL means useful facts exist but important details remain missing; NOT_FOUND means it is not established by the supplied evidence.\n"
        "- missing_information must identify only genuine gaps after analyzing all supplied evidence.\n"
        "- Do not add recommendations or external best practices to customer_analysis.\n"
        "- recommended_approach may propose practical next steps, but only from the supplied customer evidence and identified gaps; do not introduce external facts or best practices.\n"
        "- Return JSON only."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the customer-evidence analysis engine of AI-Agent. "
            "Reason across the supplied internal evidence and produce a useful professional "
            "customer-specific synthesis. The evidence is the absolute factual boundary. "
            "Do not invent customer facts and do not add external knowledge. Return JSON only."
        ),
        input=analysis_input,
    )

    try:
        parsed = json.loads((response.output_text or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI Internal customer evidence analysis did not return valid JSON.") from exc

    customer_analysis = str(parsed.get("customer_analysis") or "").strip()
    recommended_approach = str(parsed.get("recommended_approach") or "").strip()
    if not customer_analysis:
        raise ValueError("OpenAI Internal customer evidence analysis did not return customer_analysis.")

    cleaned = []
    for item in (parsed.get("aspects") or []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().upper()
        if status not in {"FOUND", "PARTIAL", "NOT_FOUND"}:
            status = "PARTIAL"
        missing = item.get("missing_information") or []
        if not isinstance(missing, list):
            missing = [str(missing)]
        cleaned.append({
            "aspect": str(item.get("aspect") or "").strip(),
            "status": status,
            "reason": str(item.get("summary") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "missing_information": [
                str(value or "").strip()
                for value in missing
                if str(value or "").strip()
            ],
        })

    overall_status = str(parsed.get("overall_status") or "").strip().upper()
    if overall_status not in {"FOUND", "PARTIAL", "NOT_FOUND"}:
        statuses = {item["status"] for item in cleaned}
        overall_status = (
            "NOT_FOUND" if statuses == {"NOT_FOUND"}
            else "PARTIAL" if ("PARTIAL" in statuses or "NOT_FOUND" in statuses)
            else "FOUND"
        )

    return {
        "answer": customer_analysis,
        "recommended_approach": recommended_approach,
        "aspects": cleaned,
        "overall_status": overall_status,
        "model": model,
        "source_type": "OPENAI_INTERNAL_CUSTOMER_EVIDENCE_ANALYSIS",
        "openai_used": True,
        "evidence_characters_sent": total_chars,
    }

def get_internal_gap_assistance(question, interpretation, evidence_assessment):
    """
    Obtain external OpenAI assistance only for Internal Knowledge gaps.

    The returned material is advisory/external knowledge. It must remain clearly
    separated from customer/internal facts.
    """
    gap_aspects = [
        item for item in (evidence_assessment or {}).get("aspects", [])
        if item.get("status") in {"PARTIAL", "NOT_FOUND"}
    ]
    if not gap_aspects:
        return {
            "answer": "",
            "model": None,
            "source_type": "NONE",
            "openai_used": False,
            "gap_aspects": [],
        }

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    client = OpenAI(api_key=api_key)

    assistance_input = (
        "USER QUESTION:\n" + (question or "").strip() + "\n\n"
        "QUESTION INTERPRETATION:\n"
        + json.dumps(interpretation or {}, ensure_ascii=False) + "\n\n"
        "INTERNAL KNOWLEDGE GAPS:\n"
        + json.dumps(gap_aspects, ensure_ascii=False) + "\n\n"
        "Provide external assistance ONLY for these gaps. "
        "Do not claim any external information is a customer fact. "
        "Focus on missing information to collect, considerations, validation questions, "
        "and generally applicable guidance useful to complete the analysis. "
        "Be concise, professional, and structured."
    )

    response = client.responses.create(
        model=model,
        instructions=(
            "You are the External Gap Assistance service of AI-Agent. "
            "Help only with identified Internal Knowledge gaps. "
            "Never invent or state external information as customer-specific fact."
        ),
        input=assistance_input,
    )

    return {
        "answer": (response.output_text or "").strip(),
        "model": model,
        "source_type": "OPENAI_INTERNAL_GAP_ASSISTANCE",
        "openai_used": True,
        "gap_aspects": gap_aspects,
    }
