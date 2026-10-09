import re

from mentor.ai_agent_models import GenericKnowledgeItem, Term, TermAlias


def _normalize_text(value):
    return " ".join((value or "").casefold().split())


def _sentences(text):
    """
    Split stored knowledge into reusable textual statements.
    No OpenAI call is made.
    """
    text = (text or "").strip()

    if not text:
        return []

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)

    return [
        part.strip(" \t\r\n-*•")
        for part in parts
        if part.strip(" \t\r\n-*•")
    ]


def _master_concepts():
    """
    Load approved terminology dynamically from Master Knowledge.

    Nothing is hard-coded here. Terms and aliases come from the database.
    """
    concepts = []

    terms = (
        Term.objects
        .filter(is_active=True, searchable=True)
        .prefetch_related("aliases")
    )

    for term in terms:
        phrases = {term.term}

        for alias in term.aliases.filter(is_active=True):
            phrases.add(alias.alias)

        concepts.append(
            {
                "term": term.term,
                "phrases": phrases,
            }
        )

    return concepts


def analyze_generic_knowledge(generic_knowledge):
    """
    Analyze one stored GenericKnowledge record locally.

    The original OpenAI answer remains unchanged.

    This function:
    - makes NO OpenAI request;
    - uses Master Knowledge terminology dynamically;
    - finds statements containing recognized concepts/aliases;
    - creates pending GenericKnowledgeItem records;
    - does not automatically promote anything to Master Knowledge.
    """

    if generic_knowledge is None:
        raise ValueError("GenericKnowledge record is required.")

    content = (generic_knowledge.content or "").strip()

    if not content:
        return {
            "items_created": 0,
            "items_existing": 0,
            "concepts_found": 0,
            "openai_used": False,
        }

    sentences = _sentences(content)
    concepts = _master_concepts()

    created_count = 0
    existing_count = 0
    concepts_found = 0

    for concept in concepts:
        matched_sentences = []

        for sentence in sentences:
            normalized_sentence = _normalize_text(sentence)

            if any(
                re.search(
                    rf"(?<!\w){re.escape(_normalize_text(phrase))}(?!\w)",
                    normalized_sentence,
                )
                for phrase in concept["phrases"]
                if phrase
            ):
                matched_sentences.append(sentence)

        if not matched_sentences:
            continue

        concepts_found += 1

        description = " ".join(dict.fromkeys(matched_sentences)).strip()

        item, created = GenericKnowledgeItem.objects.get_or_create(
            generic_knowledge=generic_knowledge,
            concept=concept["term"],
            defaults={
                "description": description,
                "validation_status": "PENDING",
                "is_active": True,
            },
        )

        if created:
            created_count += 1
        else:
            existing_count += 1

    return {
        "items_created": created_count,
        "items_existing": existing_count,
        "concepts_found": concepts_found,
        "openai_used": False,
    }