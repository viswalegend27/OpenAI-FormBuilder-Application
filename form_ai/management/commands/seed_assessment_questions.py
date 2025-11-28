"""
Management command to seed initial assessment questions by role.
"""

from django.core.management.base import BaseCommand
from form_ai.models import AssessmentQuestionBank


ASSESSMENT_QUESTIONS = {
    "Python Intern": [
        "What is the difference between a list and a tuple in Python?",
        "Explain what a decorator is in Python and give an example of when you would use one.",
        "How does Python's garbage collection work and what is reference counting?",
    ],
    "Backend Developer": [
        "Explain the difference between SQL and NoSQL databases and when you would use each.",
        "What is a RESTful API and what are the main HTTP methods used in REST?",
        "Describe the concept of microservices and what are some advantages and disadvantages?",
    ],
    "Frontend Developer": [
        "Explain the virtual DOM in React and how it improves performance.",
        "What is the difference between state and props in React?",
        "Describe CSS Grid and CSS Flexbox. When would you use one over the other?",
    ],
    "Full Stack Developer": [
        "Describe the MVC architecture and how it applies to web applications.",
        "What is the purpose of middleware in Express.js or similar frameworks?",
        "Explain the concept of authentication vs authorization and give examples.",
    ],
    "Data Science Intern": [
        "What is the difference between supervised and unsupervised learning?",
        "Explain what feature scaling is and why it's important in machine learning.",
        "What is cross-validation and why is it important in model evaluation?",
    ],
}


class Command(BaseCommand):
    help = "Seed initial assessment questions by role"

    def handle(self, *args, **options):
        """Execute command to seed assessment questions."""
        created_count = 0
        existing_count = 0

        for role, questions in ASSESSMENT_QUESTIONS.items():
            bank, created = AssessmentQuestionBank.objects.get_or_create(
                role=role, defaults={"questions": []}
            )
            cleaned = [question.strip() for question in questions if question.strip()]
            bank.questions = cleaned
            bank.save(update_fields=["questions", "updated_at"])
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Created question bank for {role}")
                )
            else:
                existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Seeding complete: {created_count} created, {existing_count} already exist"
            )
        )
