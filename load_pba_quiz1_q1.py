from website.website_models import QuizExam, QuestionBank, QuizExamQuestion

# PMI-PBA / Quiz 1
quiz, quiz_created = QuizExam.objects.get_or_create(
    slug="pmi-pba-quiz-1",
    defaults={
        "category": "Project Management",
        "certification": "PMI-PBA",
        "title": "Quiz 1",
        "quiz_type": "quiz",
        "description": "PMI-PBA practice quiz.",
        "seconds_per_question": 80,
        "passing_score": 75,
        "show_answer_immediately": True,
        "shuffle_questions": True,
        "shuffle_choices": False,
        "strict_timer": False,
        "auto_submit_on_timeout": False,
        "status": "published",
        "is_active": True,
    },
)

# Question 1 from the supplied source screenshot.
question, question_created = QuestionBank.objects.get_or_create(
    certification="PMI-PBA",
    source_question_id="pm-tricks-premiumquiz-72-chapter-483-q1",
    defaults={
        "category": "Project Management",
        "question_type": "quiz",
        "question_format": "single_choice",
        "domain": "",
        "topic": "Business requirements and project/program initiation",
        "difficulty": "not_set",
        "question_text": (
            "Which of the following can be said about the relationship between "
            "business requirements and project or program initiation?"
        ),
        "option_a": (
            "Business requirements should be defined during project or program "
            "initiation as the same resources will be involved in both and there "
            "will be better collaboration."
        ),
        "option_b": (
            "Business requirements are typically defined prior to project or "
            "program initiation as they provide the justification for initiating them."
        ),
        "option_c": (
            "Business requirements are typically defined after project or program "
            "initiation as they reflect the value proposition of the project or program."
        ),
        "option_d": (
            "Business requirements can be defined at any time relative to project "
            "or program initiation as the charter components are the same as the "
            "business case components."
        ),
        "correct_answer": "B",
        "source_explanation": (
            "The supplied source explains that business requirements are normally "
            "defined before the portfolio component, program, or project is initiated "
            "because they establish the reason for undertaking the initiative or "
            "creating/modifying the product."
        ),
        "thestoreware_explanation": (
            "Business requirements describe the business need and justification that "
            "drives an initiative. They therefore normally exist before project or "
            "program initiation and help explain why the initiative should begin."
        ),
        "exam_tip": (
            "When a question asks about timing, distinguish the business need and "
            "justification from the later initiation of the project or program."
        ),
        "source_type": "screenshot",
        "source_reference": "PM-tricks PremiumQuiz 72 / chapter 483; source cites PMI Guide to Business Analysis, p.10",
        "status": "published",
        "is_active": True,
    },
)

link, link_created = QuizExamQuestion.objects.get_or_create(
    quiz_exam=quiz,
    question=question,
    defaults={"sort_order": 1, "points": 1},
)

print("Quiz:", quiz.id, quiz.title, "CREATED" if quiz_created else "EXISTING")
print("Question:", question.id, "CREATED" if question_created else "EXISTING")
print("Link:", link.id, "CREATED" if link_created else "EXISTING")
print("Active questions in Quiz 1:", quiz.question_links.filter(question__is_active=True).count())
print("Expected display: Question 1 of", quiz.question_links.filter(question__is_active=True).count())
