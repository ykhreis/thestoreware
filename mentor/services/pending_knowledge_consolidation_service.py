from django.utils import timezone

from mentor.ai_agent_models import GenericKnowledgeCandidate
from mentor.services.external_ai_service import analyze_pending_knowledge_pool


def analyze_pending_generic_knowledge(progress_callback=None, limit=40):
    """
    Gate 1B: analyze PENDING Generic Knowledge candidates as a semantic pool.

    SAFE BY DESIGN:
    - Does not promote GenericKnowledge.
    - Does not create GenericKnowledgeItem rows.
    - Does not change candidate status.
    - Does not delete/reject candidates.
    - Stores only the OpenAI review proposal in candidate.analysis_json.
    """
    def emit(percent, stage):
        if progress_callback:
            progress_callback(int(percent), stage)

    emit(5, "Loading pending Generic Knowledge candidates")

    candidates = list(
        GenericKnowledgeCandidate.objects
        .filter(status="PENDING")
        .order_by("created_at", "id")[:limit]
    )

    if not candidates:
        emit(100, "No PENDING Generic Knowledge candidates found")
        return {
            "analyzed": 0,
            "groups": [],
            "message": "No PENDING Generic Knowledge candidates found.",
        }

    emit(15, f"Preparing {len(candidates)} pending candidate(s) for semantic analysis")

    payload = []
    for candidate in candidates:
        payload.append({
            "candidate_id": candidate.id,
            "question": candidate.question,
            "canonical_concept": candidate.canonical_concept,
            "knowledge_aspect": candidate.knowledge_aspect,
            "canonical_description": candidate.canonical_description,
            "answer": candidate.answer,
        })

    emit(30, "OpenAI is analyzing the pending knowledge pool")
    analysis = analyze_pending_knowledge_pool(payload)

    emit(75, "Saving consolidation proposals for human review")

    groups_by_id = {
        str(group.get("group_id") or ""): group
        for group in analysis.get("groups", [])
    }
    reviews_by_candidate = {
        int(review["candidate_id"]): review
        for review in analysis.get("candidate_reviews", [])
    }

    analyzed_at = timezone.now().isoformat()
    updated = 0

    for candidate in candidates:
        review = reviews_by_candidate.get(candidate.id, {
            "candidate_id": candidate.id,
            "group_id": "",
            "relationship": "UNIQUE",
            "confidence": 0.0,
            "reason": "No model classification returned; manual review required.",
        })
        group = groups_by_id.get(str(review.get("group_id") or ""))

        current_analysis = dict(candidate.analysis_json or {})
        current_analysis["pending_consolidation"] = {
            "analyzed_at": analyzed_at,
            "model": analysis.get("model") or "",
            "source_type": analysis.get("source_type"),
            "review": review,
            "group": group,
            "safe_mode": True,
            "database_action": "NONE_REVIEW_ONLY",
        }

        GenericKnowledgeCandidate.objects.filter(pk=candidate.id).update(
            analysis_json=current_analysis,
        )
        updated += 1

    emit(95, "Pending consolidation proposal saved; no knowledge was promoted")
    emit(100, "Pending knowledge analysis completed")

    return {
        "analyzed": updated,
        "groups": analysis.get("groups", []),
        "candidate_reviews": analysis.get("candidate_reviews", []),
        "message": (
            f"Analyzed {updated} pending candidate(s) into "
            f"{len(analysis.get('groups', []))} semantic group(s). "
            "Review only: no candidate was promoted, rejected, deleted, or merged."
        ),
    }


def apply_pending_generic_knowledge_consolidation(progress_callback=None):
    """
    Apply the saved Gate 1B proposal to staging only.

    - Never creates GenericKnowledge / GenericKnowledgeItem.
    - Never deletes candidates.
    - CONFLICT groups stay PENDING.
    - One canonical candidate stays PENDING per safe semantic group.
    - Non-canonical members are closed as COMPLETED with audit history.
    """
    def emit(percent, stage):
        if progress_callback:
            progress_callback(int(percent), stage)

    emit(5, "Loading reviewed pending consolidation proposals")

    candidates = list(
        GenericKnowledgeCandidate.objects
        .filter(status="PENDING")
        .order_by("created_at", "id")
    )

    if not candidates:
        emit(100, "No PENDING candidates to consolidate")
        return {
            "applied_groups": 0,
            "closed_candidates": 0,
            "remaining_pending": 0,
            "message": "No PENDING candidates to consolidate.",
        }

    groups = {}
    unreviewed = []

    for candidate in candidates:
        consolidation = (candidate.analysis_json or {}).get("pending_consolidation") or {}
        review = consolidation.get("review") or {}
        group = consolidation.get("group") or {}
        group_id = str(group.get("group_id") or review.get("group_id") or "").strip()

        if not group_id or not group:
            unreviewed.append(candidate.id)
            continue

        groups.setdefault(group_id, {"group": group, "members": []})["members"].append(candidate)

    if unreviewed:
        raise ValueError(
            "These PENDING candidates have no complete consolidation proposal: "
            f"{unreviewed}. Run Analyze & Consolidate Pending first."
        )

    emit(20, f"Validating {len(groups)} reviewed semantic group(s)")

    applied_groups = 0
    closed_candidates = 0
    skipped_conflicts = 0
    applied_at = timezone.now().isoformat()
    total = max(1, len(groups))

    for index, (group_id, bucket) in enumerate(groups.items(), start=1):
        group = bucket["group"]
        members = bucket["members"]
        decision = str(group.get("group_decision") or "").strip().upper()

        if decision == "CONFLICT":
            skipped_conflicts += 1
            for candidate in members:
                data = dict(candidate.analysis_json or {})
                pc = dict(data.get("pending_consolidation") or {})
                pc["database_action"] = "CONFLICT_REQUIRES_HUMAN_REVIEW"
                pc["applied_at"] = applied_at
                data["pending_consolidation"] = pc
                GenericKnowledgeCandidate.objects.filter(pk=candidate.pk).update(
                    analysis_json=data
                )
            continue

        member_ids = {candidate.id for candidate in members}

        try:
            canonical_id = int(group.get("canonical_candidate_id"))
        except (TypeError, ValueError):
            canonical_id = None

        if canonical_id not in member_ids:
            raise ValueError(
                f"Group {group_id} has an invalid canonical candidate. "
                "No changes were applied to this group."
            )

        canonical = next(candidate for candidate in members if candidate.id == canonical_id)

        proposed_concept = str(group.get("proposed_concept") or "").strip()
        proposed_aspect = str(group.get("proposed_aspect") or "").strip()
        proposed_description = str(group.get("proposed_description") or "").strip()

        if proposed_concept:
            canonical.canonical_concept = proposed_concept
        if proposed_aspect:
            canonical.knowledge_aspect = proposed_aspect
        if proposed_description:
            canonical.canonical_description = proposed_description

        canonical_data = dict(canonical.analysis_json or {})
        canonical_pc = dict(canonical_data.get("pending_consolidation") or {})
        canonical_pc["database_action"] = "CANONICAL_RETAINED_PENDING_FOR_GATE_2"
        canonical_pc["applied_at"] = applied_at
        canonical_pc["consolidated_candidate_ids"] = sorted(member_ids)
        canonical_data["pending_consolidation"] = canonical_pc
        canonical.analysis_json = canonical_data

        canonical.save(update_fields=[
            "canonical_concept",
            "knowledge_aspect",
            "canonical_description",
            "analysis_json",
        ])

        for candidate in members:
            if candidate.id == canonical.id:
                continue

            data = dict(candidate.analysis_json or {})
            pc = dict(data.get("pending_consolidation") or {})
            pc["database_action"] = "CONSOLIDATED_INTO_CANONICAL"
            pc["canonical_candidate_id"] = canonical.id
            pc["applied_at"] = applied_at
            data["pending_consolidation"] = pc

            GenericKnowledgeCandidate.objects.filter(pk=candidate.pk).update(
                status="COMPLETED",
                processed_at=timezone.now(),
                promoted_generic_knowledge=None,
                error_message="",
                analysis_json=data,
            )
            closed_candidates += 1

        applied_groups += 1
        emit(
            20 + int((index / total) * 70),
            f"Applied group {group_id}; Candidate #{canonical.id} retained for Gate 2",
        )

    remaining_pending = GenericKnowledgeCandidate.objects.filter(status="PENDING").count()

    emit(95, "Staging consolidation applied; final Generic Knowledge unchanged")
    emit(100, "Apply Consolidation completed")

    return {
        "applied_groups": applied_groups,
        "closed_candidates": closed_candidates,
        "skipped_conflicts": skipped_conflicts,
        "remaining_pending": remaining_pending,
        "message": (
            f"Applied {applied_groups} reviewed group(s). "
            f"Closed {closed_candidates} redundant staging candidate(s). "
            f"{remaining_pending} candidate(s) remain PENDING for Gate 2. "
            "No final Generic Knowledge was created."
        ),
    }
