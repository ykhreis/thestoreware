import re


def _clean(text):
    return " ".join((text or "").split())


def _words(text):
    return {
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+\-/]*", text or "")
        if len(word) > 2
    }


def _deduplicate(statements):
    """
    Remove strongly overlapping statements mechanically.
    No business/domain vocabulary is used.
    """
    selected = []

    for statement in statements:
        statement = _clean(statement)
        if not statement:
            continue

        statement_words = _words(statement)
        duplicate = False

        for existing in selected:
            existing_words = _words(existing)
            if not statement_words or not existing_words:
                continue

            overlap = len(statement_words & existing_words)
            smaller = min(len(statement_words), len(existing_words))

            if smaller and overlap / smaller >= 0.72:
                duplicate = True
                break

        if not duplicate:
            selected.append(statement)

    return selected


def build_professional_brief(question, evidence):
    """
    Local presentation/synthesis layer.

    IMPORTANT:
    - zero OpenAI/API calls;
    - no fixed domain vocabulary;
    - no new facts are generated;
    - evidence wording is preserved;
    - the service only cleans, deduplicates, orders, and presents evidence.

    This deliberately remains conservative. True free-form rewriting would
    require a language model; this local layer must not pretend to invent
    semantic conclusions that are not present in the stored evidence.
    """
    evidence = _deduplicate(evidence)

    if not evidence:
        return (
            "No sufficiently relevant internal evidence was available to build "
            "a professional brief. OpenAI was not used."
        )

    question_words = _words(question)

    ranked = []
    for position, statement in enumerate(evidence):
        statement_words = _words(statement)
        question_hits = len(statement_words & question_words)
        information_density = len(statement_words)

        ranked.append(
            (
                question_hits,
                min(information_density, 100),
                -position,
                statement,
            )
        )

    ranked.sort(reverse=True)
    selected = [row[3] for row in ranked[:6]]

    lines = [
        "Professional Internal Brief",
        "",
        "Executive Summary",
    ]

    # Keep the first strongest evidence statement intact. This is a grounded
    # summary anchor, not generated prose.
    lines.append(selected[0])

    if len(selected) > 1:
        lines.extend(["", "Key Findings"])
        lines.extend(f"• {statement}" for statement in selected[1:])

    lines.extend(
        [
            "",
            "Information Basis",
            "This brief is based only on information stored in the AI-Agent "
            "database. OpenAI was not used.",
        ]
    )

    return "\n".join(lines)
