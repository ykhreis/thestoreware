from mentor.ai_agent_models import ConversationIntent, ConversationExpression

DATA = {
    "GREETING": {
        "name": "Greeting",
        "description": "Short conversational greetings that can be answered locally.",
        "expressions": [
            ("en", "hello", "Hello! 👋 How can I help you today?"),
            ("en", "hi", "Hello! 👋 How can I help you today?"),
            ("en", "hey", "Hello! 👋 How can I help you today?"),
            ("en", "good morning", "Good morning! 👋 How can I help you today?"),
            ("en", "good afternoon", "Good afternoon! 👋 How can I help you today?"),
            ("en", "good evening", "Good evening! 👋 How can I help you today?"),
            ("ar", "مرحبا", "مرحباً! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("ar", "مرحباً", "مرحباً! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("ar", "اهلا", "أهلاً وسهلاً! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("ar", "أهلا", "أهلاً وسهلاً! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("ar", "أهلاً", "أهلاً وسهلاً! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("ar", "السلام عليكم", "وعليكم السلام! 👋 كيف يمكنني مساعدتك اليوم؟"),
            ("fr", "bonjour", "Bonjour ! 👋 Comment puis-je vous aider aujourd’hui ?"),
            ("fr", "salut", "Bonjour ! 👋 Comment puis-je vous aider aujourd’hui ?"),
            ("fr", "bonsoir", "Bonsoir ! 👋 Comment puis-je vous aider aujourd’hui ?"),
        ],
    },
    "THANKS": {
        "name": "Thanks",
        "description": "Short expressions of thanks that can be answered locally.",
        "expressions": [
            ("en", "thank you", "You're welcome! 😊"),
            ("en", "thanks", "You're welcome! 😊"),
            ("en", "thanks a lot", "You're very welcome! 😊"),
            ("ar", "شكرا", "على الرحب والسعة! 😊"),
            ("ar", "شكراً", "على الرحب والسعة! 😊"),
            ("ar", "شكرا لك", "على الرحب والسعة! 😊"),
            ("ar", "شكراً لك", "على الرحب والسعة! 😊"),
            ("fr", "merci", "Avec plaisir ! 😊"),
            ("fr", "merci beaucoup", "Avec plaisir ! 😊"),
        ],
    },
    "GOODBYE": {
        "name": "Goodbye",
        "description": "Short conversational farewells that can be answered locally.",
        "expressions": [
            ("en", "bye", "Goodbye! 👋 See you again soon."),
            ("en", "goodbye", "Goodbye! 👋 See you again soon."),
            ("en", "see you", "See you soon! 👋"),
            ("ar", "مع السلامة", "مع السلامة! 👋 نراك قريباً."),
            ("ar", "الى اللقاء", "إلى اللقاء! 👋"),
            ("ar", "إلى اللقاء", "إلى اللقاء! 👋"),
            ("fr", "au revoir", "Au revoir ! 👋 À bientôt."),
            ("fr", "à bientôt", "À bientôt ! 👋"),
            ("fr", "a bientot", "À bientôt ! 👋"),
        ],
    },
}

created_intents = 0
created_expressions = 0
updated_expressions = 0

for code, item in DATA.items():
    intent, created = ConversationIntent.objects.update_or_create(
        code=code,
        defaults={
            "name": item["name"],
            "description": item["description"],
            "is_active": True,
        },
    )
    created_intents += int(created)

    for language_code, expression, response_text in item["expressions"]:
        obj, created = ConversationExpression.objects.update_or_create(
            intent=intent,
            language_code=language_code,
            expression=expression,
            request_channel="WEBSITE",
            source_name="TheStoreWare",
            defaults={
                "response_text": response_text,
                "priority": 100,
                "is_active": True,
            },
        )
        if created:
            created_expressions += 1
        else:
            updated_expressions += 1

print("Conversation data loaded successfully.")
print("New intents:", created_intents)
print("New expressions:", created_expressions)
print("Updated expressions:", updated_expressions)
print("Total TheStoreWare expressions:", ConversationExpression.objects.filter(
    request_channel="WEBSITE",
    source_name="TheStoreWare",
    is_active=True,
).count())
