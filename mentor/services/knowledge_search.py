import re

from mentor.ai_agent_models import (
    KnowledgeItem,
    KnowledgeChunk,
    Organization,
    Term,
    TermAlias,
    TermRelation,
)


def _words(text):
    """Generic tokenizer. Business vocabulary comes only from Master Knowledge."""
    return re.findall(r"\w+(?:[_+./-]\w+)*", (text or "").casefold(), flags=re.UNICODE)


def _phrase_count(text, phrase):
    """Count a phrase using generic word boundaries only."""
    text = (text or "").casefold()
    phrase = (phrase or "").strip().casefold()
    if not text or not phrase:
        return 0

    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return len(re.findall(pattern, text, flags=re.UNICODE))


def _master_query_context(query):
    """Resolve query concepts from Term, TermAlias and TermRelation only."""
    query = (query or "").strip().casefold()
    query_words = set(_words(query))

    terms = list(
        Term.objects.filter(is_active=True, searchable=True)
    )
    aliases = list(
        TermAlias.objects.select_related("term").filter(
            is_active=True,
            term__is_active=True,
            term__searchable=True,
        )
    )

    focus = {}

    for term_obj in terms:
        canonical = (term_obj.term or "").strip().casefold()
        canonical_words = set(_words(canonical))
        if canonical and canonical_words and (
            _phrase_count(query, canonical) > 0
            or canonical_words.issubset(query_words)
        ):
            focus[term_obj.id] = term_obj

    for alias_obj in aliases:
        alias = (alias_obj.alias or "").strip().casefold()
        alias_words = set(_words(alias))
        if alias and alias_words and (
            _phrase_count(query, alias) > 0
            or alias_words.issubset(query_words)
        ):
            focus[alias_obj.term_id] = alias_obj.term

    weighted_phrases = {}
    direct_focus_phrases = set()

    def add_phrase(phrase, weight):
        phrase = (phrase or "").strip().casefold()
        if not phrase:
            return
        numeric_weight = float(weight or 0)
        current = weighted_phrases.get(phrase)
        if current is None or numeric_weight > current:
            weighted_phrases[phrase] = numeric_weight

    for term_obj in focus.values():
        add_phrase(term_obj.term, term_obj.weight)
        direct_focus_phrases.add((term_obj.term or "").strip().casefold())

    if focus:
        for alias_obj in aliases:
            if alias_obj.term_id in focus:
                add_phrase(alias_obj.alias, focus[alias_obj.term_id].weight)
                direct_focus_phrases.add((alias_obj.alias or "").strip().casefold())

        relations = (
            TermRelation.objects
            .filter(
                source_term_id__in=focus.keys(),
                target_term__is_active=True,
                target_term__searchable=True,
            )
            .select_related("target_term")
        )

        related_ids = set()
        for relation in relations:
            related_ids.add(relation.target_term_id)
            add_phrase(relation.target_term.term, relation.target_term.weight)

        for alias_obj in aliases:
            if alias_obj.term_id in related_ids:
                add_phrase(alias_obj.alias, alias_obj.term.weight)

    return bool(focus), weighted_phrases, {p for p in direct_focus_phrases if p}


def _score_text(has_master_focus, weighted_phrases, query, text):
    """Rank locally. Master Knowledge weights come from the database."""
    if not text:
        return 0

    if has_master_focus:
        score = 0.0
        for phrase, weight in weighted_phrases.items():
            count = _phrase_count(text, phrase)
            if count:
                score += weight * count
        return score

    # Generic fallback when the question contains no searchable Master Knowledge concept.
    # No fixed vocabulary is used: every query word is treated uniformly.
    return float(sum(_phrase_count(text, word) for word in _words(query)))



def _literal_query_focus(query, searchable_texts):
    """
    Identify the most discriminating literal query word(s) from the selected
    corpus itself. No fixed stop-word or domain vocabulary is used.

    Words that occur in fewer searchable records are more discriminating.
    Only words actually present in the corpus can become literal focus.
    """
    query_words = set(_words(query))
    if not query_words:
        return set()

    document_frequency = {}
    for word in query_words:
        frequency = sum(
            1 for searchable in searchable_texts
            if _phrase_count(searchable, word) > 0
        )
        if frequency > 0:
            document_frequency[word] = frequency

    if not document_frequency:
        return set()

    minimum_frequency = min(document_frequency.values())
    return {
        word for word, frequency in document_frequency.items()
        if frequency == minimum_frequency
    }


def _contains_literal_focus(text, literal_focus):
    if not literal_focus:
        return False
    return any(_phrase_count(text, word) > 0 for word in literal_focus)

def search_knowledge(query, limit=5, source_id=None, source_ids=None, organization_id=None, progress_callback=None, investigation=False):
    """
    Search AI-Agent internal knowledge with ZERO OpenAI/API usage.

    Master Knowledge controls recognized concepts, aliases, relations and weights.
    Customer/organization and source remain database filters.

    investigation=True keeps the same relevance rules but allows a broader
    evidence set for aspect-by-aspect Internal / Customer investigation.
    """
    def emit(percent, stage):
        if progress_callback:
            progress_callback(percent, stage)

    query = (query or "").strip()
    source_ids = [int(value) for value in (source_ids or ([source_id] if source_id else []))]
    if not query:
        return {"items": [], "chunks": []}

    emit(30, "Understanding question locally")
    has_master_focus, weighted_phrases, direct_focus_phrases = _master_query_context(query)
    emit(40, "Master Knowledge concepts and relationships analyzed")

    items_qs = (
        KnowledgeItem.objects
        .filter(is_active=True, validation_status="VALIDATED")
        .select_related("organization")
        .prefetch_related("topics")
    )

    if organization_id:
        allowed_org_ids = [organization_id] + list(
            Organization.objects.filter(is_default=True, is_active=True)
            .values_list("id", flat=True)
        )
        items_qs = items_qs.filter(organization_id__in=allowed_org_ids)

    chunks_qs = (
        KnowledgeChunk.objects
        .filter(source__is_active=True)
        .select_related("source", "source__organization")
    )

    if source_ids:
        chunks_qs = chunks_qs.filter(source_id__in=source_ids)

    if organization_id:
        allowed_org_ids = [organization_id] + list(
            Organization.objects.filter(is_default=True, is_active=True)
            .values_list("id", flat=True)
        )
        chunks_qs = chunks_qs.filter(source__organization_id__in=allowed_org_ids)

    emit(50, "Searching direct internal evidence")
    item_searchables = []
    for item in items_qs:
        topics = " ".join(topic.name for topic in item.topics.all())
        searchable = f"{item.title}\n{item.content}\n{topics}\n{item.source_reference}"
        item_searchables.append((item, searchable))

    chunk_searchables = []
    for chunk in chunks_qs:
        searchable = (
            f"{chunk.source.name}\n"
            f"{chunk.source.source_type}\n"
            f"{chunk.source.source_reference}\n"
            f"{chunk.content}"
        )
        chunk_searchables.append((chunk, searchable))

    corpus_texts = [value for _, value in item_searchables + chunk_searchables]

    # Relevance gate for recognized Master Knowledge concepts:
    # the selected organization/document must contain the concept itself (or one
    # of its approved aliases). Related terms may improve ranking only after this
    # direct relevance requirement is satisfied.
    if has_master_focus and direct_focus_phrases:
        corpus_has_direct_focus = any(
            _phrase_count(searchable, phrase) > 0
            for searchable in corpus_texts
            for phrase in direct_focus_phrases
        )
        if not corpus_has_direct_focus:
            return {"items": [], "chunks": []}

    literal_focus = _literal_query_focus(query, corpus_texts)

    ranked_items = []
    for item, searchable in item_searchables:
        # If a discriminating literal concept exists in the selected corpus,
        # it is the retrieval gate. Generic question words cannot retrieve
        # unrelated records on their own.
        if has_master_focus and direct_focus_phrases:
            direct_score = sum(
                _phrase_count(searchable, phrase)
                for phrase in direct_focus_phrases
            )
            if direct_score <= 0:
                continue
            literal_score = float(direct_score)
        elif literal_focus:
            if not _contains_literal_focus(searchable, literal_focus):
                continue
            literal_score = sum(
                _phrase_count(searchable, word) for word in literal_focus
            )
        else:
            literal_score = 0.0

        master_score = (
            _score_text(has_master_focus, weighted_phrases, query, searchable)
            if has_master_focus else 0.0
        )

        score = literal_score + master_score
        if score > 0:
            item.local_score = score
            ranked_items.append(item)

    ranked_chunks = []
    for chunk, searchable in chunk_searchables:
        if has_master_focus and direct_focus_phrases:
            direct_score = sum(
                _phrase_count(searchable, phrase)
                for phrase in direct_focus_phrases
            )
            if direct_score <= 0:
                continue
            literal_score = float(direct_score)
        elif literal_focus:
            if not _contains_literal_focus(searchable, literal_focus):
                continue
            literal_score = sum(
                _phrase_count(searchable, word) for word in literal_focus
            )
        else:
            literal_score = 0.0

        master_score = (
            _score_text(has_master_focus, weighted_phrases, query, searchable)
            if has_master_focus else 0.0
        )

        score = literal_score + master_score
        if score > 0:
            chunk.local_score = score
            ranked_chunks.append(chunk)

    ranked_items.sort(key=lambda obj: (-obj.local_score, obj.id))
    ranked_chunks.sort(key=lambda obj: (-obj.local_score, obj.id))

    # Internal investigation expansion:
    # Keep the normal high-precision ranking above, then supplement the selected
    # evidence with records containing approved Master Knowledge relations of the
    # recognized concept. This helps questions such as "current CCTV environment"
    # collect related evidence (for example, approved related infrastructure,
    # storage or connectivity concepts) even when every useful record does not
    # repeat the direct query phrase.
    #
    # Important:
    # - organization/source filters remain unchanged;
    # - only DB-approved Term/TermAlias/TermRelation vocabulary is used;
    # - direct matches remain first;
    # - no OpenAI/API/embedding call is introduced.

    direct_limit = max(limit, 12) if investigation else limit
    selected_items = ranked_items[:direct_limit]
    selected_chunks = ranked_chunks[:direct_limit]

    emit(60, "Investigating related internal evidence")
    if has_master_focus and weighted_phrases:
        direct_phrases = set(direct_focus_phrases)
        related_phrases = {
            phrase: weight
            for phrase, weight in weighted_phrases.items()
            if phrase not in direct_phrases
        }

        if related_phrases:
            selected_item_ids = {obj.id for obj in selected_items}
            selected_chunk_ids = {obj.id for obj in selected_chunks}

            related_items = []
            for item, searchable in item_searchables:
                if item.id in selected_item_ids:
                    continue

                related_score = sum(
                    float(weight or 0) * _phrase_count(searchable, phrase)
                    for phrase, weight in related_phrases.items()
                )
                if related_score > 0:
                    item.local_score = related_score
                    related_items.append(item)

            related_chunks = []
            for chunk, searchable in chunk_searchables:
                if chunk.id in selected_chunk_ids:
                    continue

                related_score = sum(
                    float(weight or 0) * _phrase_count(searchable, phrase)
                    for phrase, weight in related_phrases.items()
                )
                if related_score > 0:
                    chunk.local_score = related_score
                    related_chunks.append(chunk)

            related_items.sort(key=lambda obj: (-obj.local_score, obj.id))
            related_chunks.sort(key=lambda obj: (-obj.local_score, obj.id))

            # Add investigative evidence without allowing relation expansion to
            # overwhelm the direct evidence. The caller can still apply its own
            # final evidence selection.
            investigation_limit = max(4, direct_limit) if investigation else max(2, limit)

            selected_items.extend(related_items[:investigation_limit])
            selected_chunks.extend(related_chunks[:investigation_limit])

    emit(
        70,
        f"Evidence ranked: {len(selected_items)} knowledge item(s), "
        f"{len(selected_chunks)} content record(s)"
    )
    return {
        "items": selected_items,
        "chunks": selected_chunks,
    }
