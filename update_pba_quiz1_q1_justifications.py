from website.website_models import QuestionBank

SOURCE_QUESTION_ID = "pm-tricks-premiumquiz-72-chapter-483-q1"

try:
    q = QuestionBank.objects.get(
        certification="PMI-PBA",
        source_question_id=SOURCE_QUESTION_ID,
    )
except QuestionBank.DoesNotExist:
    raise SystemExit(
        f"Question not found: certification=PMI-PBA, source_question_id={SOURCE_QUESTION_ID}"
    )

# IMPORTANT:
# These explanations are stored content. The voice layer will only read them.
# It will not decide which answer is correct or generate explanations at runtime.

q.option_a_explanation = (
    "This is not the best answer. Business requirements represent the business need "
    "and justification for an initiative, so they should not first be defined during "
    "project or program initiation merely because the same resources may be involved."
)

q.option_b_explanation = (
    "This is the correct answer. Business requirements are normally established before "
    "project or program initiation because they describe the business need and provide "
    "the justification for undertaking the initiative."
)

q.option_c_explanation = (
    "This is incorrect because it reverses the normal sequence. The business need and "
    "requirements help justify why the project or program should be initiated; they are "
    "not normally created only after initiation."
)

q.option_d_explanation = (
    "This is incorrect. Business requirements and the project charter do not serve the "
    "same purpose. Business requirements express the business need and justification, "
    "while initiation formally authorizes the project or program; therefore the timing "
    "is not arbitrary."
)

q.thestoreware_explanation = (
    "Business requirements describe the business need and justification that drives an "
    "initiative. They therefore normally exist before project or program initiation and "
    "help explain why the initiative should begin."
)

q.exam_tip = (
    "When a question asks about sequence, distinguish the business need and justification "
    "from the later formal initiation of the project or program."
)

q.save(update_fields=[
    "option_a_explanation",
    "option_b_explanation",
    "option_c_explanation",
    "option_d_explanation",
    "thestoreware_explanation",
    "exam_tip",
    "updated_at",
])

print(f"Updated Question ID: {q.id}")
print(f"Certification: {q.certification}")
print(f"Correct answer: {q.correct_answer}")
print("A explanation:", "OK" if q.option_a_explanation else "MISSING")
print("B explanation:", "OK" if q.option_b_explanation else "MISSING")
print("C explanation:", "OK" if q.option_c_explanation else "MISSING")
print("D explanation:", "OK" if q.option_d_explanation else "MISSING")
print("Question 1 justification update completed successfully.")
