# workflow.py

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from django.db import transaction

from .helper.views_helper import AppError
from .models import CandidateAnswer, InterviewForm, TechnicalAssessment, VoiceConversation
from .views_schema_ import AssessmentExtractor, RoleQuestionGenerator

logger = logging.getLogger(__name__)

# Auto-generated starter interview template used when the workspace is empty.
STARTER_INTERVIEW_TEMPLATE = {
    "title": "Sample Interview Plan",
    "summary": "Starter interview generated automatically. Update it to match your role.",
    "ai_prompt": "",
    "questions": [
        "Can you introduce yourself and share your current focus area?",
        "Tell me about a recent project that best represents your strengths.",
        "What tools or languages are you most comfortable working with right now?",
    ],
}


class InterviewFlow:
    """Operations tied to InterviewForm nodes."""

    @staticmethod
    def create_form(
        *,
        title: str,
        summary: str = "",
        ai_prompt: str = "",
        questions: Iterable[str],
    ) -> InterviewForm:
        title_value = (title or "").strip()
        if not title_value:
            raise AppError("Interview title is required", status=400)
        cleaned_questions = [
            str(item).strip() for item in questions if isinstance(item, str) and item.strip()
        ]
        if not cleaned_questions:
            raise AppError("Add at least one interview question", status=400)

        interview = InterviewForm.objects.create(
            title=title_value,
            summary=(summary or "").strip(),
            ai_prompt=(ai_prompt or "").strip(),
        )
        interview.append_questions(cleaned_questions)
        interview.save(update_fields=["question_schema", "updated_at"])
        logger.info(
            "[FLOW:INTERVIEW] Created interview %s with %d questions",
            interview.id,
            len(cleaned_questions),
        )
        return interview

    @staticmethod
    def delete_form(form: InterviewForm) -> Dict[str, Any]:
        question_count = len(form.get_question_entries())
        title = form.title
        interview_id = str(form.id)
        form.delete()
        remaining = InterviewForm.objects.count()
        logger.info(
            "[FLOW:INTERVIEW] Deleted interview %s (%s) with %d questions",
            interview_id,
            title,
            question_count,
        )
        return {
            "interview_id": interview_id,
            "title": title,
            "deleted_questions": question_count,
            "remaining_interviews": remaining,
        }

    @staticmethod
    def remove_question(form: InterviewForm, question_id: str) -> int:
        questions = form.get_question_entries()
        if len(questions) <= 1:
            raise AppError(
                "At least one question is required per interview. Add another question before deleting this one.",
                status=400,
            )

        if not form.remove_question(question_id):
            raise AppError("Question not found on this interview", status=404)

        form.save(update_fields=["question_schema", "updated_at"])
        remaining = len(form.get_question_entries())
        logger.info(
            "[FLOW:INTERVIEW] Removed question %s from interview %s (remaining=%d)",
            question_id,
            form.id,
            remaining,
        )
        return remaining

    @staticmethod
    def ensure_seed_interview() -> InterviewForm | None:
        """Create a starter interview when none exist so the UI always has content."""
        if InterviewForm.objects.exists():
            return None

        template = STARTER_INTERVIEW_TEMPLATE
        try:
            interview = InterviewFlow.create_form(
                title=template["title"],
                summary=template.get("summary", ""),
                ai_prompt=template.get("ai_prompt", ""),
                questions=template["questions"],
            )
            logger.info("[FLOW:INTERVIEW] Seeded starter interview %s", interview.id)
            return interview
        except AppError as exc:
            logger.error("[FLOW:INTERVIEW] Failed to seed starter interview: %s", exc)
        except Exception as exc:  # pragma: no cover - safety log
            logger.exception("[FLOW:INTERVIEW] Unexpected error seeding interview: %s", exc)
        return None


class ConversationFlow:
    """Operations tied to VoiceConversation nodes."""

    @staticmethod
    def save_conversation(
        *,
        messages: List[Dict[str, Any]],
        session_id: str | None,
        interview_form: InterviewForm | None,
    ) -> VoiceConversation:
        conversation = VoiceConversation.objects.create(
            session_id=session_id,
            messages=messages,
            interview_form=interview_form,
        )
        logger.info(
            "[FLOW:CONVERSATION] Stored conversation %s (messages=%d, interview=%s)",
            conversation.pk,
            len(messages),
            interview_form.id if interview_form else "-",
        )
        return conversation

    @staticmethod
    def apply_analysis(conversation: VoiceConversation, extracted_data: Mapping[str, Any]) -> VoiceConversation:
        conversation.extracted_info = dict(extracted_data or {})
        conversation.save(update_fields=["extracted_info", "updated_at"])
        logger.info(
            "[FLOW:CONVERSATION] Analysis saved for %s with fields: %s",
            conversation.pk,
            ", ".join(conversation.extracted_info.keys()),
        )
        return conversation


class AssessmentFlow:
    """Operations tied to TechnicalAssessment and CandidateAnswer nodes."""

    @staticmethod
    @transaction.atomic
    def generate_for_conversation(
        conversation: VoiceConversation,
        *,
        target_count: int,
        generator: RoleQuestionGenerator | None = None,
    ) -> Tuple[TechnicalAssessment, List[str]]:
        if not conversation.extracted_info:
            raise AppError(
                "No user data available. Please complete the voice interview first.",
                status=400,
            )

        interview_form = conversation.interview_form
        if not interview_form:
            raise AppError(
                "Interview reference missing. Please create a new voice interview from the builder.",
                status=400,
            )

        role_label = (interview_form.title or "").strip()
        if not role_label:
            raise AppError("Interview form is missing a title", status=400)

        generator = generator or RoleQuestionGenerator()
        style_examples = interview_form.question_texts()[: target_count * 2]

        questions_list = AssessmentFlow._generate_questions(
            generator, role_label, target_count, style_examples
        )
        if len(questions_list) < target_count:
            raise AppError(
                "Could not generate assessment questions. Please adjust your interview questions and try again.",
                status=500,
            )

        assessment = TechnicalAssessment.objects.create(
            conversation=conversation,
            interview_form=interview_form,
        )
        assessment.set_questions(questions_list)
        assessment.save(update_fields=["questions", "updated_at"])
        logger.info(
            "[FLOW:ASSESSMENT] Created assessment %s for conversation %s (%d questions, title=%s)",
            assessment.id,
            conversation.pk,
            len(questions_list),
            role_label,
        )
        return assessment, questions_list

    @staticmethod
    def _generate_questions(
        generator: RoleQuestionGenerator,
        role: str,
        target_count: int,
        style_examples: List[str] | None,
    ) -> List[str]:
        questions = generator.generate(role, style_examples or None, count=target_count)
        questions = [q.strip() for q in questions if q and q.strip()]
        if len(questions) >= target_count:
            return questions

        logger.warning(
            "[FLOW:ASSESSMENT] Only generated %d/%d questions for title '%s'. Retrying without examples.",
            len(questions),
            target_count,
            role,
        )
        retry = [
            q.strip() for q in generator.generate(role, None, count=target_count) if q and q.strip()
        ]
        return retry if len(retry) >= target_count else questions

    @staticmethod
    def save_transcript(assessment: TechnicalAssessment, messages: List[Dict[str, Any]], session_id: str | None) -> int:
        assessment.transcript = messages
        assessment.save(update_fields=["transcript", "updated_at"])
        logger.info(
            "[FLOW:ASSESSMENT] Transcript saved for %s (messages=%d, session=%s)",
            assessment.id,
            len(messages),
            session_id or "-",
        )
        return len(messages)

    @staticmethod
    @transaction.atomic
    def analyze_answers(
        assessment: TechnicalAssessment,
        *,
        qa_mapping: Mapping[str, Any] | None = None,
        extractor: AssessmentExtractor | None = None,
    ) -> Dict[str, Any]:
        question_entries = assessment.get_question_entries()
        if not question_entries:
            raise AppError("Assessment has no questions", status=400)

        if qa_mapping is not None and not isinstance(qa_mapping, Mapping):
            raise AppError("qa_mapping must be an object", status=400)

        answers_source: Mapping[str, Any]
        if qa_mapping:
            answers_source = qa_mapping
            logger.info(
                "[FLOW:ASSESSMENT] Using provided qa_mapping for assessment %s (%d entries)",
                assessment.id,
                len(qa_mapping),
            )
        else:
            extractor = extractor or AssessmentExtractor()
            questions_payload = [
                {"index": entry["sequence_number"], "q": entry["text"]}
                for entry in question_entries
            ]
            answers_source = extractor.extract_answers(assessment.transcript, questions_payload)

        saved_answers = AssessmentFlow._persist_answers(
            assessment,
            question_entries,
            answers_source,
        )

        assessment.is_completed = True
        assessment.save(update_fields=["is_completed", "updated_at"])
        logger.info("[FLOW:ASSESSMENT] Marked assessment %s as completed", assessment.id)

        return {
            "answers": saved_answers,
            "total_questions": len(question_entries),
            "answered_questions": assessment.answered_count,
        }

    @staticmethod
    def _persist_answers(
        assessment: TechnicalAssessment,
        question_entries: List[Dict[str, Any]],
        answers_source: Mapping[str, Any],
    ) -> Dict[str, str]:
        answer_sheet, _ = CandidateAnswer.objects.get_or_create(assessment=assessment)
        answers_map = dict(answer_sheet.answers or {})
        saved: Dict[str, str] = {}

        for entry in question_entries:
            question_key = entry["id"]
            fallback_keys = [
                question_key,
                f"q{entry['sequence_number']}",
                question_key.lower(),
            ]
            answer_text = ""
            for key in fallback_keys:
                if key in answers_source and answers_source[key] is not None:
                    answer_text = answers_source[key]
                    break
            normalized = (str(answer_text or "").strip()) or "NIL"
            answers_map[question_key] = normalized
            saved[question_key] = normalized
            logger.debug("[FLOW:ASSESSMENT] Stored answer for question %s", question_key)

        answer_sheet.answers = answers_map
        answer_sheet.save(update_fields=["answers", "updated_at"])
        return saved

    @staticmethod
    def delete_assessment(assessment: TechnicalAssessment) -> Tuple[VoiceConversation, int]:
        conversation = assessment.conversation
        assessment.delete()
        remaining = conversation.assessments.count()
        logger.info(
            "[FLOW:ASSESSMENT] Deleted assessment %s (conversation=%s remaining=%d)",
            assessment.id,
            conversation.id,
            remaining,
        )
        return conversation, remaining
