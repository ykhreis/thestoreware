from django.db import transaction

from mentor.ai_agent_models import AnalysisKnowledge, KnowledgeChunk, KnowledgeItem, KnowledgeSource, Topic


@transaction.atomic
def reset_knowledge_base():
    """
    Delete knowledge/test content while preserving application configuration,
    users, groups, permissions, AgentTypes, and Organizations.

    Physical uploaded files are intentionally NOT deleted here.
    """
    counts = {
        "analysis_knowledge": AnalysisKnowledge.objects.count(),
        "knowledge_chunks": KnowledgeChunk.objects.count(),
        "knowledge_items": KnowledgeItem.objects.count(),
        "knowledge_sources": KnowledgeSource.objects.count(),
        "topics": Topic.objects.count(),
    }

    AnalysisKnowledge.objects.all().delete()
    KnowledgeChunk.objects.all().delete()
    KnowledgeItem.objects.all().delete()
    KnowledgeSource.objects.all().delete()
    Topic.objects.all().delete()

    return counts
