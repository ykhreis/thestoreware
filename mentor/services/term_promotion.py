from django.db import transaction

from mentor.ai_agent_models import Term, TermCandidate


@transaction.atomic
def promote_term_candidate(candidate):
    """
    Promote one reviewed TermCandidate into the trusted Master Knowledge Term table.

    This service is fully local:
    - No OpenAI/API calls.
    - No fixed business vocabulary.
    - Classification comes from the candidate's database-driven TermType.
    """
    if isinstance(candidate, int):
        candidate = TermCandidate.objects.select_for_update().get(pk=candidate)
    else:
        candidate = (
            TermCandidate.objects.select_for_update()
            .get(pk=candidate.pk)
        )

    term_text = (candidate.term_text or "").strip()
    if not term_text:
        raise ValueError("Candidate term text is required.")

    if candidate.suggested_term_type_id is None:
        raise ValueError(
            f'Candidate "{term_text}" must have a Suggested Term Type before approval.'
        )

    existing_term = Term.objects.filter(term__iexact=term_text).first()

    if existing_term:
        changed_fields = []

        if existing_term.term_type_id is None:
            existing_term.term_type = candidate.suggested_term_type
            changed_fields.append("term_type")

        if not existing_term.is_active:
            existing_term.is_active = True
            changed_fields.append("is_active")

        if changed_fields:
            changed_fields.append("updated_at")
            existing_term.save(update_fields=changed_fields)

        term = existing_term
        created = False
    else:
        term = Term.objects.create(
            term=term_text,
            term_type=candidate.suggested_term_type,
            description=(candidate.suggested_meaning or "").strip(),
            searchable=True,
            weight=1.00,
            is_active=True,
        )
        created = True

    candidate.is_reviewed = True
    candidate.is_approved = True
    candidate.save(update_fields=["is_reviewed", "is_approved", "updated_at"])

    return {
        "candidate_id": candidate.id,
        "term_id": term.id,
        "term": term.term,
        "created": created,
    }
