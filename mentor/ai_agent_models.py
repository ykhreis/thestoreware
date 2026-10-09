from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class Organization(models.Model):
    ORGANIZATION_TYPES = [
        ("GENERIC", "Generic / All Customers"),
        ("CUSTOMER", "Customer"),
        ("INTERNAL", "Internal"),
        ("PARTNER", "Partner"),
        ("VENDOR", "Vendor"),
        ("OTHER", "Other"),
    ]

    name = models.CharField(max_length=200, unique=True)
    organization_type = models.CharField(
        max_length=20,
        choices=ORGANIZATION_TYPES,
        default="CUSTOMER",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Topic(models.Model):
    ORIGIN_TYPES = [
        ("MANUAL", "Manual"),
        ("AI", "AI Discovered"),
        ("SYSTEM", "System"),
    ]

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    origin_type = models.CharField(
        max_length=20,
        choices=ORIGIN_TYPES,
        default="MANUAL"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "topic"
        ordering = ["name"]

    def __str__(self):
        return self.name


class KnowledgeItem(models.Model):
    SOURCE_TYPES = [
        ("DATABASE", "Database"),
        ("DOCUMENT", "Document"),
        ("USER", "User"),
        ("OPENAI", "OpenAI"),
        ("LEARNED", "Learned Knowledge"),
        ("OTHER", "Other"),
    ]

    VALIDATION_STATUS = [
        ("PENDING", "Pending Validation"),
        ("VALIDATED", "Validated"),
        ("REJECTED", "Rejected"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="knowledge_items",
        null=True,
        blank=True,
    )
    topics = models.ManyToManyField(
        Topic,
        related_name="knowledge_items",
        blank=True
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPES,
        default="DATABASE"
    )
    source_reference = models.TextField(
        blank=True,
        help_text="Reference to the original source of this knowledge."
    )
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS,
        default="PENDING"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_item"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class KnowledgeSource(models.Model):
    STATUS_TYPES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("PROCESSED", "Processed"),
        ("FAILED", "Failed"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="knowledge_sources",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=50)
    source_reference = models.TextField(
        blank=True,
        help_text="Reference to the original file, document, system, or source."
    )
    processing_status = models.CharField(
        max_length=20,
        choices=STATUS_TYPES,
        default="PENDING"
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_knowledge_sources",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_source"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class KnowledgeChunk(models.Model):
    source = models.ForeignKey(
        KnowledgeSource,
        on_delete=models.CASCADE,
        related_name="chunks"
    )
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "knowledge_chunk"
        ordering = ["source_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "chunk_index"],
                name="unique_source_chunk_index"
            )
        ]

    def __str__(self):
        return f"{self.source.name} - Chunk {self.chunk_index}"


class AnalysisKnowledge(models.Model):
    ORIGIN_TYPES = [
        ("INTERNAL", "Internal Analysis"),
        ("OPENAI", "Explicit OpenAI Research"),
        ("USER", "User Entered"),
    ]

    VALIDATION_STATUS = [
        ("PENDING", "Pending Validation"),
        ("VALIDATED", "Validated"),
        ("REJECTED", "Rejected"),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="analysis_knowledge",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    origin_type = models.CharField(
        max_length=20,
        choices=ORIGIN_TYPES,
        default="INTERNAL",
    )
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS,
        default="PENDING",
    )
    evidence_sources = models.ManyToManyField(
        KnowledgeSource,
        related_name="analysis_knowledge",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_analysis_knowledge",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "analysis_knowledge"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class GenericKnowledge(models.Model):
    """
    Reusable generic knowledge obtained outside customer-specific documents.

    This store is intentionally separate from customer/internal knowledge.
    It can be searched before making an explicit OpenAI API request.
    """

    SOURCE_TYPES = [
        ("OPENAI", "OpenAI"),
        ("USER", "User Entered"),
        ("OTHER", "Other"),
    ]

    VALIDATION_STATUS = [
        ("PENDING", "Pending Validation"),
        ("VALIDATED", "Validated"),
        ("REJECTED", "Rejected"),
    ]

    question = models.TextField(
        help_text="Original generic question that produced or introduced this knowledge."
    )
    title = models.CharField(max_length=255)
    content = models.TextField()

    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPES,
        default="OPENAI",
    )
    model_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="External AI model used to obtain this knowledge, when applicable.",
    )
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS,
        default="PENDING",
    )

    usage_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_generic_knowledge",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_generic_knowledge",
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "generic_knowledge"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class GenericKnowledgeItem(models.Model):
    """
    Structured reusable knowledge extracted from a GenericKnowledge source.

    GenericKnowledge keeps the original question/full external answer.
    GenericKnowledgeItem keeps the analyzed concept and description that
    AI-Agent can reuse locally.
    """

    VALIDATION_STATUS = [
        ("PENDING", "Pending Validation"),
        ("VALIDATED", "Validated"),
        ("REJECTED", "Rejected"),
    ]

    generic_knowledge = models.ForeignKey(
        GenericKnowledge,
        on_delete=models.CASCADE,
        related_name="knowledge_items",
    )

    concept = models.CharField(
        max_length=255,
        help_text="Reusable concept or keyword extracted from the source knowledge.",
    )
    knowledge_aspect = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Specific aspect of the concept covered by this knowledge, "
            "identified dynamically during knowledge analysis."
        ),
    )

    semantic_embedding = VectorField(
        dimensions=384,
        null=True,
        blank=True,
        help_text="Local semantic embedding for Generic Knowledge matching.",
    )

    embedding_model = models.CharField(
        max_length=100,
        blank=True,
        help_text="Embedding model used to generate semantic_embedding.",
    )
    embedding_dimensions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of dimensions in semantic_embedding.",
    )

    description = models.TextField(
        help_text="Reusable description or definition of the extracted concept.",
    )

    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUS,
        default="PENDING",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "generic_knowledge_item"
        ordering = ["concept"]
        constraints = [
            models.UniqueConstraint(
                fields=["generic_knowledge", "concept"],
                name="unique_generic_knowledge_concept",
            )
        ]

    def __str__(self):
        return self.concept


class GenericKnowledgeCandidate(models.Model):
    """
    Staging area for externally learned generic knowledge.

    A candidate is stored here first so the interactive web request does not
    need to create final GenericKnowledge/GenericKnowledgeItem rows or generate
    local semantic embeddings. A later processing step can validate, de-duplicate,
    embed, and promote the candidate into the reusable Generic Knowledge store.
    """

    STATUS_TYPES = [
        ("PENDING", "Pending Processing"),
        ("PROCESSING", "Processing"),
        ("COMPLETED", "Completed"),
        ("REJECTED", "Rejected"),
        ("FAILED", "Failed"),
    ]

    question = models.TextField()
    canonical_concept = models.CharField(max_length=255, blank=True)
    knowledge_aspect = models.CharField(max_length=255, blank=True)
    canonical_description = models.TextField(blank=True)
    answer = models.TextField()

    analysis_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured analysis returned for the externally learned knowledge.",
    )

    model_name = models.CharField(max_length=100, blank=True)
    source_type = models.CharField(max_length=20, default="OPENAI")

    status = models.CharField(
        max_length=20,
        choices=STATUS_TYPES,
        default="PENDING",
        db_index=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_generic_knowledge_candidates",
        null=True,
        blank=True,
    )

    promoted_generic_knowledge = models.ForeignKey(
        GenericKnowledge,
        on_delete=models.SET_NULL,
        related_name="source_candidates",
        null=True,
        blank=True,
        help_text="Final GenericKnowledge record created when this candidate is promoted.",
    )

    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "generic_knowledge_candidate"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return self.canonical_concept or self.question[:100]


# ============================================================
# Global / Master Knowledge Vocabulary
# ============================================================

class TermType(models.Model):
    """
    Dynamic classification for vocabulary terms.
    Examples are stored as database records, not fixed Python choices.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    allow_context_classification = models.BooleanField(
        default=True,
        help_text=(
            "Allow this TermType to influence contextual classification "
            "of new term candidates."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "term_type"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Term(models.Model):
    """
    Master vocabulary used by AI-Agent to interpret questions locally.
    Search behavior is data-driven through searchable and weight.
    """
    term = models.CharField(max_length=255, unique=True)
    term_type = models.ForeignKey(
        TermType,
        on_delete=models.PROTECT,
        related_name="terms",
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True)
    searchable = models.BooleanField(default=True)
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.00,
        help_text="Relative importance of this term during local search."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "term"
        ordering = ["term"]

    def __str__(self):
        return self.term


class TermAlias(models.Model):
    """
    Alternative spelling, acronym, abbreviation, or synonym for a Term.
    """
    term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    alias = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "term_alias"
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} -> {self.term.term}"


class TermRelation(models.Model):
    """
    Dynamic relationship between two vocabulary terms.

    relation_type is deliberately stored as data rather than using
    fixed Django choices, so relationship vocabulary can grow over time.
    """
    source_term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="outgoing_relations",
    )
    target_term = models.ForeignKey(
        Term,
        on_delete=models.CASCADE,
        related_name="incoming_relations",
    )
    relation_type = models.CharField(max_length=100)
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.00,
        help_text="Strength/relevance of this relationship."
    )
    is_bidirectional = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "term_relation"
        ordering = ["source_term_id", "target_term_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_term", "target_term", "relation_type"],
                name="unique_term_relation",
            )
        ]

    def __str__(self):
        return (
            f"{self.source_term.term} -[{self.relation_type}]-> "
            f"{self.target_term.term}"
        )


class TermCandidate(models.Model):
    """
    Unknown or newly discovered vocabulary awaiting review/promotion
    into the trusted master Term table.
    """
    term_text = models.CharField(max_length=255, unique=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    found_in_question = models.BooleanField(default=False)
    found_in_document = models.BooleanField(default=False)
    suggested_meaning = models.TextField(blank=True)
    suggested_term_type = models.ForeignKey(
        TermType,
        on_delete=models.SET_NULL,
        related_name="term_candidates",
        null=True,
        blank=True,
    )
    source_reference = models.TextField(blank=True)
    is_reviewed = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "term_candidate"
        ordering = ["-occurrence_count", "term_text"]

    def __str__(self):
        return self.term_text
