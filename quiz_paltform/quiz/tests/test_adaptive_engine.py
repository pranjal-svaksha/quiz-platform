
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone

from quiz.models import (
    Job, JobLevel, Question, QuestionOption,
    Quiz, Candidate, Assessment, TestSession, QuizQuestion, Response
)
from quiz.views import (
    process_answer, get_next_question, _complete_assessment,
    CORRECT_MARKS, STEPDOWN_PENALTY, BUFFER_BORROW_PENALTY
)


# ============================================================
#  BASE: creates a minimal quiz + session for each test
# ============================================================
class AdaptiveEngineTestBase(TestCase):

    def setUp(self):
        # Job + Level
        self.job = Job.objects.create(name="Python")
        self.primary_level = JobLevel.objects.create(
            job=self.job, level_name="Junior", jd_text="Junior Python dev"
        )
        self.secondary_level = JobLevel.objects.create(
            job=self.job, level_name="Senior", jd_text="Senior Python dev"
        )

        # Quiz
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.primary_level,
            secondary_job_level=self.secondary_level,
            easy_count=3,
            medium_count=3,
            hard_count=3,
            secondary_exam_count=3,
            total_questions_limit=12,
            is_finalized=True,
        )

        # Create questions and QuizQuestion entries
        self._create_quiz_questions()

        # Candidate + Assessment + Session
        self.candidate = Candidate.objects.create(name="Test User", email="test@test.com")
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4()),
            test_duration_mins=60,
            status=Assessment.Status.IN_PROGRESS,
            started_at=timezone.now(),
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            easy_pool=self.quiz.easy_count,
            medium_pool=self.quiz.medium_count,
            hard_pool=self.quiz.hard_count,
            current_difficulty='Easy',
        )

    def _create_quiz_questions(self):
        """Create primary + buffer questions for all levels."""
        difficulties = ['Easy', 'Medium', 'Hard']
        for diff in difficulties:
            for role in [QuizQuestion.Role.PRIMARY, QuizQuestion.Role.BUFFER]:
                for i in range(3):
                    q = Question.objects.create(
                        job_level=self.primary_level,
                        question_prompt=f"{diff} {role} Q{i}",
                        difficulty=diff,
                        type='MCQ',
                    )
                    opt = QuestionOption.objects.create(
                        question=q, option_text="Correct", is_correct=True
                    )
                    QuizQuestion.objects.create(
                        quiz=self.quiz,
                        question=q,
                        difficulty=diff,
                        role=role,
                        pool=QuizQuestion.Pool.PRIMARY_POOL,
                        order=i,
                    )

        # Secondary questions (Hard difficulty from secondary_level)
        for role in [QuizQuestion.Role.PRIMARY, QuizQuestion.Role.BUFFER]:
            for i in range(3):
                q = Question.objects.create(
                    job_level=self.secondary_level,
                    question_prompt=f"Secondary {role} Q{i}",
                    difficulty='Hard',
                    type='MCQ',
                )
                QuestionOption.objects.create(
                    question=q, option_text="Correct", is_correct=True
                )
                QuizQuestion.objects.create(
                    quiz=self.quiz,
                    question=q,
                    difficulty='Hard',
                    role=role,
                    pool=QuizQuestion.Pool.SECONDARY_POOL,
                    order=i,
                )

    def _fake_answer(self, is_correct, is_skipped=False):
        """Simulate one answer cycle without HTTP."""
        question, terminated = get_next_question(self.session, self.quiz)
        if terminated or question is None:
            return None, terminated

        self.session.current_question = question
        Response.objects.create(
            test_session=self.session,
            question=question,
            is_correct=is_correct,
            is_skipped=is_skipped,
        )
        result = process_answer(self.session, is_correct=is_correct, is_skipped=is_skipped)
        self.session.total_q_answered += 1
        self.session.save()
        return result, False


# ============================================================
#  TEST CLASS 1: process_answer — streak + difficulty logic
# ============================================================
class TestProcessAnswer(AdaptiveEngineTestBase):

    def test_correct_increments_consecutive_correct(self):
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 1)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_wrong_increments_consecutive_wrong(self):
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.consecutive_wrong, 1)
        self.assertEqual(self.session.consecutive_correct, 0)

    def test_skip_counts_as_wrong(self):
        process_answer(self.session, is_correct=False, is_skipped=True)
        self.assertEqual(self.session.consecutive_wrong, 1)

    def test_correct_resets_wrong_streak(self):
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_wrong_resets_correct_streak(self):
        self.session.consecutive_correct = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 0)

    def test_two_correct_promotes(self):
        self.session.consecutive_correct = 1
        result = process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(result, 'promote')
        self.assertEqual(self.session.current_difficulty, 'Medium')

    def test_two_wrong_demotes(self):
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_wrong = 1
        result = process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(result, 'demote')
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_promote_resets_both_counters(self):
        self.session.consecutive_correct = 1
        self.session.consecutive_wrong = 0
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 0)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_demote_resets_both_counters(self):
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 0)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_alternating_stays_at_same_level(self):
        for i in range(6):
            process_answer(self.session, is_correct=(i % 2 == 0), is_skipped=False)
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_correct_score_easy(self):
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.running_score, CORRECT_MARKS['Easy'])

    def test_correct_score_medium(self):
        self.session.current_difficulty = 'Medium'
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.running_score, CORRECT_MARKS['Medium'])

    def test_correct_score_hard(self):
        self.session.current_difficulty = 'Hard'
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.running_score, CORRECT_MARKS['Hard'])

    def test_correct_score_secondary(self):
        self.session.current_difficulty = 'Secondary'
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.running_score, CORRECT_MARKS['Secondary'])

    def test_stepdown_hard_to_medium_penalty(self):
        self.session.current_difficulty = 'Hard'
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.running_score, STEPDOWN_PENALTY[('Hard', 'Medium')])

    def test_stepdown_medium_to_easy_penalty(self):
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.running_score, STEPDOWN_PENALTY[('Medium', 'Easy')])

    def test_stepdown_secondary_to_hard_no_penalty(self):
        self.session.current_difficulty = 'Secondary'
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.running_score, 0)

    def test_score_can_go_negative(self):
        self.session.running_score = 0
        self.session.current_difficulty = 'Hard'
        self.session.consecutive_wrong = 1
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertLess(self.session.running_score, 0)

    def test_no_demote_below_easy(self):
        self.session.current_difficulty = 'Easy'
        self.session.consecutive_wrong = 1
        result = process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_no_promote_above_secondary(self):
        self.session.current_difficulty = 'Secondary'
        self.session.consecutive_correct = 1
        result = process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Secondary')

    def test_is_gate_passed_set_on_medium(self):
        self.session.consecutive_correct = 1
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertTrue(self.session.is_gate_passed)

    def test_full_promote_chain(self):
        """2 correct at each level should reach Secondary."""
        for _ in range(8):
            self.session.save()
            process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.current_difficulty, 'Secondary')


# ============================================================
#  TEST CLASS 2: get_next_question — pool + fallback logic
# ============================================================
class TestGetNextQuestion(AdaptiveEngineTestBase):

    def test_returns_question_at_easy(self):
        question, terminated = get_next_question(self.session, self.quiz)
        self.assertIsNotNone(question)
        self.assertFalse(terminated)

    def test_question_not_repeated(self):
        seen = set()
        for _ in range(3):
            q, _ = get_next_question(self.session, self.quiz)
            if q:
                Response.objects.create(
                    test_session=self.session, question=q,
                    is_correct=True, is_skipped=False
                )
                self.assertNotIn(q.id, seen)
                seen.add(q.id)

    def test_buffer_question_applies_penalty(self):
        # Exhaust all primary Easy questions
        primary_qs = QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy',
            pool=QuizQuestion.Pool.PRIMARY_POOL,
            role=QuizQuestion.Role.PRIMARY,
        )
        for qq in primary_qs:
            Response.objects.create(
                test_session=self.session,
                question=qq.question,
                is_correct=True,
                is_skipped=False,
            )

        score_before = self.session.running_score
        get_next_question(self.session, self.quiz)
        self.assertEqual(
            self.session.running_score,
            score_before + BUFFER_BORROW_PENALTY['Easy']
        )

    def test_buffer_borrow_shrinks_next_pool(self):
        primary_qs = QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy',
            pool=QuizQuestion.Pool.PRIMARY_POOL,
            role=QuizQuestion.Role.PRIMARY,
        )
        for qq in primary_qs:
            Response.objects.create(
                test_session=self.session,
                question=qq.question,
                is_correct=True,
                is_skipped=False,
            )
        medium_pool_before = self.session.medium_pool
        get_next_question(self.session, self.quiz)
        self.assertEqual(self.session.medium_pool, medium_pool_before - 1)

    def test_terminates_when_all_exhausted(self):
        # Answer every question in the quiz
        all_qs = QuizQuestion.objects.filter(quiz=self.quiz)
        for qq in all_qs:
            Response.objects.create(
                test_session=self.session,
                question=qq.question,
                is_correct=True,
                is_skipped=False,
            )
        question, terminated = get_next_question(self.session, self.quiz)
        self.assertIsNone(question)
        self.assertTrue(terminated)
        self.assertFalse(self.session.is_active)

    def test_fallback_to_lower_level_on_exhaustion(self):
        # Set to Medium, exhaust all Medium questions
        self.session.current_difficulty = 'Medium'
        self.session.save()
        medium_qs = QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Medium',
            pool=QuizQuestion.Pool.PRIMARY_POOL,
        )
        for qq in medium_qs:
            Response.objects.create(
                test_session=self.session,
                question=qq.question,
                is_correct=False,
                is_skipped=False,
            )
        question, terminated = get_next_question(self.session, self.quiz)
        self.assertIsNotNone(question)
        self.assertFalse(terminated)
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_fallback_resets_streaks(self):
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_correct = 1
        self.session.consecutive_wrong = 1
        self.session.save()
        medium_qs = QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Medium',
            pool=QuizQuestion.Pool.PRIMARY_POOL,
        )
        for qq in medium_qs:
            Response.objects.create(
                test_session=self.session,
                question=qq.question,
                is_correct=False,
                is_skipped=False,
            )
        get_next_question(self.session, self.quiz)
        self.assertEqual(self.session.consecutive_correct, 0)
        self.assertEqual(self.session.consecutive_wrong, 0)


# ============================================================
#  TEST CLASS 3: full quiz simulation end-to-end
# ============================================================
class TestFullQuizSimulation(AdaptiveEngineTestBase):

    def test_quiz_ends_at_limit(self):
        """All correct answers — should end at total_questions_limit."""
        for i in range(self.quiz.total_questions_limit + 5):
            if self.session.total_q_answered >= self.quiz.total_questions_limit:
                break
            result, terminated = self._fake_answer(is_correct=True)
            if terminated:
                break
        self.assertGreaterEqual(
            self.session.total_q_answered,
            self.quiz.total_questions_limit
        )

    def test_complete_assessment_sets_status(self):
        _complete_assessment(self.assessment, self.session)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)

    def test_complete_assessment_sets_final_score(self):
        self.session.running_score = 10
        self.session.save()
        _complete_assessment(self.assessment, self.session)
        self.assessment.refresh_from_db()
        self.assertIsNotNone(self.assessment.final_score)

    def test_complete_assessment_clears_current_question(self):
        q, _ = get_next_question(self.session, self.quiz)
        self.session.current_question = q
        self.session.save()
        _complete_assessment(self.assessment, self.session)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.current_question)

    def test_score_accumulates_correctly(self):
        """2 easy correct (+1 each) → promote → 2 medium wrong (-1 penalty) = score 1"""
        # 2 correct Easy
        self.session.save()
        process_answer(self.session, is_correct=True, is_skipped=False)  # +1
        process_answer(self.session, is_correct=True, is_skipped=False)  # +1, promote
        # now at Medium, 2 wrong → demote (-1)
        process_answer(self.session, is_correct=False, is_skipped=False)
        process_answer(self.session, is_correct=False, is_skipped=False)  # demote -1
        self.assertEqual(self.session.running_score, 1)  # 1+1-1 = 1

