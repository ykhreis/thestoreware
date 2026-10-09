from mentor.ai_agent_models import KnowledgeItem


def save_candidate_knowledge(
    title,
    content,
    source_reference="",
    agent_type=None,
    topics=None,
):
    """
    Save useful analysis as candidate knowledge for human validation.

    Safety / governance rules:
    - Candidate knowledge is always PENDING.
    - Candidate knowledge receives no embedding at creation time.
    - AgentType is optional.
    - Nothing becomes trusted/searchable as validated knowledge automatically.
    """
    title = (title or "").strip()
    content = (content or "").strip()
    source_reference = (source_reference or "").strip()

    if not title:
        raise ValueError("Candidate knowledge title is required.")

    if not content:
        raise ValueError("Candidate knowledge content is required.")

    item = KnowledgeItem.objects.create(
        agent_type=agent_type,
        title=title,
        content=content,
        source_type="LEARNED",
        source_reference=source_reference,
        validation_status="PENDING",
        embedding=None,
        is_active=True,
    )

    if topics:
        item.topics.set(topics)

    return item


def validate_candidate_knowledge(item):
    """
    Mark a PENDING candidate as VALIDATED.

    Embedding generation is intentionally NOT performed here.
    A separate controlled step can embed newly validated knowledge.
    """
    if item.validation_status != "PENDING":
        raise ValueError(
            f"Only PENDING knowledge can be validated. "
            f"Current status: {item.validation_status}"
        )

    item.validation_status = "VALIDATED"
    item.save(update_fields=["validation_status", "updated_at"])

    return item


def reject_candidate_knowledge(item):
    """
    Mark a PENDING candidate as REJECTED.

    Rejected knowledge remains available for audit/history but is not
    considered trusted knowledge by the normal validated search flow.
    """
    if item.validation_status != "PENDING":
        raise ValueError(
            f"Only PENDING knowledge can be rejected. "
            f"Current status: {item.validation_status}"
        )

    item.validation_status = "REJECTED"
    item.embedding = None
    item.save(
        update_fields=[
            "validation_status",
            "embedding",
            "updated_at",
        ]
    )

    return item
