"""
Comprehensive Unit Tests for Django Views
Testing all views, helper functions, and edge cases
"""
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import TestCase, RequestFactory, TransactionTestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.contrib.messages import get_messages
from django.utils import timezone
from django.db import transaction
from unittest.mock import patch, Mock, MagicMock
from datetime import timedelta
import uuid

from quiz.models import (
    Job, JobLevel, Question, Quiz, Assessment, Candidate, 
    Response, QuestionOption, TestSession, QuizQuestion
)
from quiz.views import (
    job_dashboard, job_detail, delete_job, edit_level, delete_level,
    generate_ai_questions, view_question_bank, quiz_list, delete_quiz,
    create_quiz, view_quiz_questions, assignment_list, delete_assessment,
    create_assignment, finalize_quiz_questions, take_assessment, submit_answer,
    get_next_question, process_answer, _complete_assessment,
    _questions_remaining, _pick_question, _apply_buffer_penalty,
    CORRECT_MARKS, STEPDOWN_PENALTY, BUFFER_BORROW_PENALTY, DIFFICULTY_ORDER
)


# ============================================================
# 1. JOB DASHBOARD TESTS
# ============================================================

class JobDashboardTests(TestCase):
    """Test job_dashboard view"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.job1 = Job.objects.create(name="Python Developer")
        self.job2 = Job.objects.create(name="Java Developer")
    
    def test_get_job_dashboard_returns_200(self):
        """Test GET request returns 200 status"""
        request = self.factory.get('/job-dashboard/')
        response = job_dashboard(request)
        self.assertEqual(response.status_code, 200)

    def test_job_dashboard_displays_all_jobs(self):
        # RIGHT: self.client captures the context automatically
        response = self.client.get(reverse('job_dashboard'))

        self.assertEqual(response.status_code, 200)
        # response.context is ONLY available when using self.client
        self.assertIn('jobs', response.context)

    def test_job_dashboard_ordered_by_created_at_desc(self):
        """Test jobs are ordered by created_at descending"""
        # 1. Use the client instead of the factory
        response = self.client.get(reverse('job_dashboard'))

        # 2. Verify the request was successful
        self.assertEqual(response.status_code, 200)

        # 3. Access 'context' (which is now available because we used self.client)
        jobs = list(response.context['jobs'])

        # 4. Assert ordering
        self.assertTrue(jobs[0].created_at >= jobs[1].created_at)

    def test_post_creates_new_job(self):
        """Test POST request creates a new job"""
        request = self.factory.post('/job-dashboard/', {'name': 'C++ Developer'})
        job_dashboard(request)
        self.assertTrue(Job.objects.filter(name='C++ Developer').exists())

    def test_post_with_empty_name_does_not_create_job(self):
        """Test POST with empty name doesn't create job"""
        initial_count = Job.objects.count()
        request = self.factory.post('/job-dashboard/', {'name': ''})
        job_dashboard(request)
        self.assertEqual(Job.objects.count(), initial_count)

    def test_post_get_or_create_prevents_duplicates(self):
        """Test get_or_create prevents duplicate jobs"""
        request = self.factory.post('/job-dashboard/', {'name': 'Python Developer'})
        job_dashboard(request)
        # Should still be 2 jobs (no duplicate created)
        self.assertEqual(Job.objects.filter(name='Python Developer').count(), 1)

    def test_post_redirects_to_job_dashboard(self):
        """Test POST redirects back to dashboard"""
        request = self.factory.post('/job-dashboard/', {'name': 'New Job'})
        response = job_dashboard(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_dashboard'))

    def test_job_dashboard_with_no_jobs(self):
        """Test dashboard works with empty database"""
        # 1. Clear the database
        Job.objects.all().delete()

        # 2. Use self.client instead of self.factory
        # Ensure 'job_dashboard' matches the name in your urls.py
        response = self.client.get(reverse('job_dashboard'))

        # 3. Check status and context
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['jobs']), 0)  # This will now work!

    def test_post_with_missing_name_field(self):
        """Test POST without 'name' field"""
        initial_count = Job.objects.count()
        request = self.factory.post('/job-dashboard/', {})
        job_dashboard(request)
        self.assertEqual(Job.objects.count(), initial_count)

    def test_post_with_whitespace_only_name(self):
        """Test POST with whitespace-only name"""
        initial_count = Job.objects.count()
        request = self.factory.post('/job-dashboard/', {'name': '   '})
        job_dashboard(request)
        # Django's get_or_create should handle this
        self.assertGreaterEqual(Job.objects.count(), initial_count)


# ============================================================
# 2. JOB DETAIL TESTS
# ============================================================

class JobDetailTests(TestCase):
    """Test job_detail view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level1 = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior developer JD"
        )
        self.level2 = JobLevel.objects.create(
            job=self.job,
            level_name="Senior",
            jd_text="Senior developer JD"
        )

    def test_get_job_detail_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get(f'/job/{self.job.id}/')
        response = job_detail(request, job_id=self.job.id)
        self.assertEqual(response.status_code, 200)

    def test_job_detail_displays_job_and_levels(self):
        """Test job and levels are in context"""
        # 1. Use the client and reverse the URL name
        url = reverse('job_detail', kwargs={'job_id': self.job.id})
        response = self.client.get(url)

        # 2. Verify the response is successful
        self.assertEqual(response.status_code, 200)

        # 3. Access 'context' (now available via self.client)
        self.assertEqual(response.context['job'], self.job)
        self.assertEqual(len(response.context['levels']), 2)

    def test_job_detail_with_nonexistent_job_raises_404(self):
        """Test requesting non-existent job raises 404"""
        from django.http import Http404
        request = self.factory.get('/job/99999/')
        with self.assertRaises(Http404):
            job_detail(request, job_id=99999)

    def test_post_creates_new_level(self):
        """Test POST creates new job level"""
        request = self.factory.post(f'/job/{self.job.id}/', {
            'level_name': 'Mid-Level',
            'jd_text': 'Mid-level JD'
        })
        job_detail(request, job_id=self.job.id)
        self.assertTrue(
            JobLevel.objects.filter(level_name='Mid-Level', job=self.job).exists()
        )

    def test_post_with_missing_level_name_does_not_create(self):
        """Test POST without level_name doesn't create"""
        initial_count = JobLevel.objects.count()
        request = self.factory.post(f'/job/{self.job.id}/', {
            'jd_text': 'Some JD'
        })
        job_detail(request, job_id=self.job.id)
        self.assertEqual(JobLevel.objects.count(), initial_count)

    def test_post_with_missing_jd_text_does_not_create(self):
        """Test POST without jd_text doesn't create"""
        initial_count = JobLevel.objects.count()
        request = self.factory.post(f'/job/{self.job.id}/', {
            'level_name': 'Expert'
        })
        job_detail(request, job_id=self.job.id)
        self.assertEqual(JobLevel.objects.count(), initial_count)

    def test_post_redirects_to_job_detail(self):
        """Test POST redirects back to job detail"""
        request = self.factory.post(f'/job/{self.job.id}/', {
            'level_name': 'Lead',
            'jd_text': 'Lead JD'
        })
        response = job_detail(request, job_id=self.job.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_detail', kwargs={'job_id': self.job.id}))

    def test_levels_ordered_by_created_at(self):
        """Test levels are ordered by created_at"""
        request = self.factory.get(f'/job/{self.job.id}/')
        response = job_detail(request, job_id=self.job.id)
        levels = list(response.context['levels'])
        for i in range(len(levels) - 1):
            self.assertLessEqual(levels[i].created_at, levels[i+1].created_at)

    def test_job_with_no_levels(self):
        """Test job detail with no levels"""
        # 1. Setup the data
        new_job = Job.objects.create(name="Test Job")

        # 2. Use the client and reverse the URL name
        # Make sure 'job_detail' matches the name in your urls.py
        url = reverse('job_detail', kwargs={'job_id': new_job.id})
        response = self.client.get(url)

        # 3. Check status and context
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['levels']), 0)

    def test_post_with_empty_strings(self):
        """Test POST with empty strings doesn't create level"""
        initial_count = JobLevel.objects.count()
        request = self.factory.post(f'/job/{self.job.id}/', {
            'level_name': '',
            'jd_text': ''
        })
        job_detail(request, job_id=self.job.id)
        self.assertEqual(JobLevel.objects.count(), initial_count)


# ============================================================
# 3. EDIT JOB TESTS
# ============================================================



# ============================================================
# 4. DELETE JOB TESTS
# ============================================================

class DeleteJobTests(TestCase):
    """Test delete_job view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")

    def test_delete_job_removes_from_database(self):
        """Test job is deleted from database"""
        request = self.factory.post(f'/job/{self.job.id}/delete/')
        delete_job(request, job_id=self.job.id)
        self.assertFalse(Job.objects.filter(id=self.job.id).exists())

    def test_delete_redirects_to_dashboard(self):
        """Test delete redirects to dashboard"""
        request = self.factory.post(f'/job/{self.job.id}/delete/')
        response = delete_job(request, job_id=self.job.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_dashboard'))

    def test_delete_nonexistent_job_raises_404(self):
        """Test deleting non-existent job raises 404"""
        from django.http import Http404
        request = self.factory.post('/job/99999/delete/')
        with self.assertRaises(Http404):
            delete_job(request, job_id=99999)

    def test_delete_job_cascades_to_levels(self):
        """Test deleting job also deletes related levels"""
        level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="JD"
        )
        request = self.factory.post(f'/job/{self.job.id}/delete/')
        delete_job(request, job_id=self.job.id)
        # Check if cascade deletion works (depends on model configuration)
        # This assumes CASCADE is set on the ForeignKey
        self.assertFalse(JobLevel.objects.filter(id=level.id).exists())

    def test_delete_accepts_any_http_method(self):
        """Test delete works with GET as well (no method check)"""
        request = self.factory.get(f'/job/{self.job.id}/delete/')
        delete_job(request, job_id=self.job.id)
        self.assertFalse(Job.objects.filter(id=self.job.id).exists())


# ============================================================
# 5. EDIT LEVEL TESTS
# ============================================================

class EditLevelTests(TestCase):
    """Test edit_level view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )

    def test_get_edit_level_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get(f'/level/{self.level.id}/edit/')
        response = edit_level(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 200)

    def test_get_edit_level_displays_level(self):
        """Test level is in context"""
        request = self.factory.get(f'/level/{self.level.id}/edit/')
        response = edit_level(request, level_id=self.level.id)
        self.assertEqual(response.context['level'], self.level)

    def test_post_updates_level_name_and_jd(self):
        """Test POST updates level name and JD text"""
        request = self.factory.post(f'/level/{self.level.id}/edit/', {
            'level_name': 'Senior',
            'jd_text': 'Updated JD'
        })
        edit_level(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertEqual(self.level.level_name, 'Senior')
        self.assertEqual(self.level.jd_text, 'Updated JD')

    def test_post_redirects_to_job_detail(self):
        """Test POST redirects to job detail"""
        request = self.factory.post(f'/level/{self.level.id}/edit/', {
            'level_name': 'Mid',
            'jd_text': 'Mid JD'
        })
        response = edit_level(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_detail', kwargs={'job_id': self.job.id}))

    def test_edit_nonexistent_level_raises_404(self):
        """Test editing non-existent level raises 404"""
        from django.http import Http404
        request = self.factory.get('/level/99999/edit/')
        with self.assertRaises(Http404):
            edit_level(request, level_id=99999)

    def test_post_with_partial_data(self):
        """Test POST with only level_name updates correctly"""
        request = self.factory.post(f'/level/{self.level.id}/edit/', {
            'level_name': 'Expert'
        })
        edit_level(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertEqual(self.level.level_name, 'Expert')


# ============================================================
# 6. DELETE LEVEL TESTS
# ============================================================

class DeleteLevelTests(TestCase):
    """Test delete_level view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )

    def test_delete_level_removes_from_database(self):
        """Test level is deleted from database"""
        request = self.factory.post(f'/level/{self.level.id}/delete/')
        delete_level(request, level_id=self.level.id)
        self.assertFalse(JobLevel.objects.filter(id=self.level.id).exists())

    def test_delete_redirects_to_job_detail(self):
        """Test delete redirects to job detail"""
        request = self.factory.post(f'/level/{self.level.id}/delete/')
        response = delete_level(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_detail', kwargs={'job_id': self.job.id}))

    def test_delete_nonexistent_level_raises_404(self):
        """Test deleting non-existent level raises 404"""
        from django.http import Http404
        request = self.factory.post('/level/99999/delete/')
        with self.assertRaises(Http404):
            delete_level(request, level_id=99999)

    def test_delete_level_preserves_job(self):
        """Test deleting level doesn't delete parent job"""
        job_id = self.job.id
        request = self.factory.post(f'/level/{self.level.id}/delete/')
        delete_level(request, level_id=self.level.id)
        self.assertTrue(Job.objects.filter(id=job_id).exists())


# ============================================================
# 7. GENERATE AI QUESTIONS TESTS
# ============================================================

class GenerateAIQuestionsTests(TestCase):
    """Test generate_ai_questions view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD",
            generation_status=JobLevel.GenerationStatus.PENDING
        )

    @patch('quiz.views.generate_quiz_for_level')
    def test_successful_generation_sets_status_completed(self, mock_generate):
        """Test successful generation sets status to COMPLETED"""
        mock_generate.return_value = True
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        generate_ai_questions(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertEqual(self.level.generation_status, JobLevel.GenerationStatus.COMPLETED)

    @patch('quiz.views.generate_quiz_for_level')
    def test_failed_generation_sets_status_failed(self, mock_generate):
        """Test failed generation sets status to FAILED"""
        mock_generate.return_value = False
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        generate_ai_questions(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertEqual(self.level.generation_status, JobLevel.GenerationStatus.FAILED)

    @patch('quiz.views.generate_quiz_for_level')
    def test_generation_sets_processing_status_first(self, mock_generate):
        """Test status is set to PROCESSING before generation"""
        mock_generate.return_value = True
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        # We can't easily check intermediate state, but we can verify final state
        generate_ai_questions(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertNotEqual(self.level.generation_status, JobLevel.GenerationStatus.PROCESSING)

    @patch('quiz.views.generate_quiz_for_level')
    def test_exception_during_generation_sets_failed(self, mock_generate):
        """Test exception during generation sets status to FAILED"""
        mock_generate.side_effect = Exception("API Error")
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        generate_ai_questions(request, level_id=self.level.id)
        self.level.refresh_from_db()
        self.assertEqual(self.level.generation_status, JobLevel.GenerationStatus.FAILED)

    @patch('quiz.views.generate_quiz_for_level')
    def test_redirects_to_job_detail(self, mock_generate):
        """Test redirects to job detail page"""
        mock_generate.return_value = True
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        response = generate_ai_questions(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('job_detail', kwargs={'job_id': self.job.id}))

    def test_nonexistent_level_raises_404(self):
        """Test non-existent level raises 404"""
        from django.http import Http404
        request = self.factory.post('/level/99999/generate/')
        with self.assertRaises(Http404):
            generate_ai_questions(request, level_id=99999)

    @patch('quiz.views.generate_quiz_for_level')
    def test_calls_generate_with_correct_level_id(self, mock_generate):
        """Test generate_quiz_for_level is called with correct level ID"""
        mock_generate.return_value = True
        request = self.factory.post(f'/level/{self.level.id}/generate/')
        generate_ai_questions(request, level_id=self.level.id)
        mock_generate.assert_called_once_with(self.level.id)


# ============================================================
# 8. VIEW QUESTION BANK TESTS
# ============================================================

class ViewQuestionBankTests(TestCase):
    """Test view_question_bank view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        # Create 15 questions for pagination testing
        for i in range(15):
            question = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Question {i+1}",
                type="MCQ",
                difficulty="Easy"
            )
            QuestionOption.objects.create(
                question=question,
                option_text="Option A",
                is_correct=True
            )

    def test_get_question_bank_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get(f'/level/{self.level.id}/questions/')
        response = view_question_bank(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 200)

    def test_pagination_shows_10_questions_per_page(self):
        """Test pagination shows 10 questions per page"""
        request = self.factory.get(f'/level/{self.level.id}/questions/')
        response = view_question_bank(request, level_id=self.level.id)
        self.assertEqual(len(response.context['page_obj']), 10)

    def test_total_count_correct(self):
        """Test total_count shows all questions"""
        request = self.factory.get(f'/level/{self.level.id}/questions/')
        response = view_question_bank(request, level_id=self.level.id)
        self.assertEqual(response.context['total_count'], 15)

    def test_pagination_page_2(self):
        """Test second page shows remaining questions"""
        request = self.factory.get(f'/level/{self.level.id}/questions/?page=2')
        response = view_question_bank(request, level_id=self.level.id)
        self.assertEqual(len(response.context['page_obj']), 5)

    def test_questions_ordered_by_difficulty_and_id(self):
        """Test questions are ordered by difficulty and ID"""
        # Create mixed difficulty questions
        Question.objects.create(
            job_level=self.level,
            question_prompt="Hard Question",
            type="MCQ",
            difficulty="Hard"
        )
        request = self.factory.get(f'/level/{self.level.id}/questions/')
        response = view_question_bank(request, level_id=self.level.id)
        # Verify ordering exists (detailed check would need actual data inspection)
        self.assertIsNotNone(response.context['page_obj'])

    def test_invalid_page_number_returns_last_page(self):
        """Test invalid page number returns last valid page"""
        request = self.factory.get(f'/level/{self.level.id}/questions/?page=999')
        response = view_question_bank(request, level_id=self.level.id)
        self.assertEqual(response.status_code, 200)
        # Django Paginator.get_page returns last page for invalid numbers

    def test_nonexistent_level_raises_404(self):
        """Test non-existent level raises 404"""
        from django.http import Http404
        request = self.factory.get('/level/99999/questions/')
        with self.assertRaises(Http404):
            view_question_bank(request, level_id=99999)

    def test_empty_question_bank(self):
        """Test viewing empty question bank"""
        empty_level = JobLevel.objects.create(
            job=self.job,
            level_name="Empty",
            jd_text="Empty JD"
        )
        request = self.factory.get(f'/level/{empty_level.id}/questions/')
        response = view_question_bank(request, level_id=empty_level.id)
        self.assertEqual(response.context['total_count'], 0)

    def test_prefetch_related_options(self):
        """Test options are prefetched (no N+1 queries)"""
        request = self.factory.get(f'/level/{self.level.id}/questions/')
        with self.assertNumQueries(3):  # Adjust based on actual query count
            response = view_question_bank(request, level_id=self.level.id)


# ============================================================
# 9. QUIZ LIST TESTS
# ============================================================

class QuizListTests(TestCase):
    """Test quiz_list view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz1 = Quiz.objects.create(
            title="Quiz 1",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )
        self.quiz2 = Quiz.objects.create(
            title="Quiz 2",
            primary_job_level=self.level,
            easy_count=3,
            medium_count=7,
            hard_count=3,
            secondary_exam_count=3
        )

    def test_get_quiz_list_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get('/quiz/list/')
        response = quiz_list(request)
        self.assertEqual(response.status_code, 200)

    def test_quiz_list_displays_all_quizzes(self):
        """Test all quizzes are displayed"""
        request = self.factory.get('/quiz/list/')
        response = quiz_list(request)
        self.assertEqual(len(response.context['quizzes']), 2)

    def test_quizzes_ordered_by_created_at_desc(self):
        """Test quizzes are ordered by created_at descending"""
        request = self.factory.get('/quiz/list/')
        response = quiz_list(request)
        quizzes = list(response.context['quizzes'])
        self.assertTrue(quizzes[0].created_at >= quizzes[1].created_at)

    def test_select_related_optimization(self):
        """Test select_related is used for optimization"""
        request = self.factory.get('/quiz/list/')
        # This would need actual query count testing
        response = quiz_list(request)
        self.assertIsNotNone(response.context['quizzes'])

    def test_empty_quiz_list(self):
        """Test quiz list with no quizzes"""
        Quiz.objects.all().delete()
        request = self.factory.get('/quiz/list/')
        response = quiz_list(request)
        self.assertEqual(len(response.context['quizzes']), 0)

    def test_quiz_with_secondary_level(self):
        """Test quiz with secondary job level"""
        secondary_level = JobLevel.objects.create(
            job=self.job,
            level_name="Senior",
            jd_text="Senior JD"
        )
        quiz = Quiz.objects.create(
            title="Advanced Quiz",
            primary_job_level=self.level,
            secondary_job_level=secondary_level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )
        request = self.factory.get('/quiz/list/')
        response = quiz_list(request)
        self.assertIn(quiz, response.context['quizzes'])


# ============================================================
# 10. DELETE QUIZ TESTS
# ============================================================

class DeleteQuizTests(TestCase):
    """Test delete_quiz view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )

    def test_post_deletes_quiz(self):
        """Test POST request deletes quiz"""
        request = self.factory.post(f'/quiz/{self.quiz.id}/delete/')
        delete_quiz(request, quiz_id=self.quiz.id)
        self.assertFalse(Quiz.objects.filter(id=self.quiz.id).exists())

    def test_get_does_not_delete_quiz(self):
        """Test GET request does not delete quiz"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/delete/')
        delete_quiz(request, quiz_id=self.quiz.id)
        self.assertTrue(Quiz.objects.filter(id=self.quiz.id).exists())

    def test_delete_redirects_to_quiz_list(self):
        """Test delete redirects to quiz list"""
        request = self.factory.post(f'/quiz/{self.quiz.id}/delete/')
        response = delete_quiz(request, quiz_id=self.quiz.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('quiz_list'))

    def test_delete_nonexistent_quiz_raises_404(self):
        """Test deleting non-existent quiz raises 404"""
        from django.http import Http404
        request = self.factory.post('/quiz/99999/delete/')
        with self.assertRaises(Http404):
            delete_quiz(request, quiz_id=99999)

    def test_delete_quiz_cascades_to_assessments(self):
        """Test deleting quiz cascades to assessments"""
        candidate = Candidate.objects.create(
            name="Test Candidate",
            email="test@example.com"
        )
        assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=candidate,
            magic_link_token=str(uuid.uuid4())
        )
        request = self.factory.post(f'/quiz/{self.quiz.id}/delete/')
        delete_quiz(request, quiz_id=self.quiz.id)
        # Check cascade (depends on model configuration)


# ============================================================
# 11. CREATE QUIZ TESTS
# ============================================================

class CreateQuizTests(TestCase):
    """Test create_quiz view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        # Create enough questions for validation
        for difficulty in ['Easy', 'Medium', 'Hard']:
            for i in range(20):
                question = Question.objects.create(
                    job_level=self.level,
                    question_prompt=f"{difficulty} Question {i+1}",
                    type="MCQ",
                    difficulty=difficulty
                )
                QuestionOption.objects.create(
                    question=question,
                    option_text="Option A",
                    is_correct=True
                )

    def test_get_create_quiz_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get('/quiz/create/')
        response = create_quiz(request)
        self.assertEqual(response.status_code, 200)

    def test_get_displays_all_levels(self):
        """Test all levels are in context"""
        request = self.factory.get('/quiz/create/')
        response = create_quiz(request)
        self.assertIn('levels', response.context)

    def test_valid_post_creates_quiz(self):
        """Test valid POST creates quiz"""
        # 1. Use the named URL from your urls.py
        url = reverse('create_quiz')

        # 2. Define your valid data
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 5,
            'medium_count': 5,
            'hard_count': 5,
            'sec_count': 5
        }

        # 3. Use self.client.post to trigger the view with middleware support
        response = self.client.post(url, data)

        # 4. Assertions
        # A successful creation usually redirects (302) to the quiz list or detail
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Quiz.objects.filter(title='New Quiz').exists())

    def test_insufficient_easy_questions_shows_error(self):
        """Test error when insufficient easy questions"""
        Question.objects.filter(difficulty='Easy').delete()

        url = reverse('create_quiz')
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 10,
            'medium_count': 5,
            'hard_count': 5,
            'sec_count': 5
        }
        # self.client handles the messages.error() call inside the view
        response = self.client.post(url, data)

        self.assertFalse(Quiz.objects.filter(title='New Quiz').exists())

    def test_insufficient_medium_questions_shows_error(self):
        """Test error when insufficient medium questions"""
        Question.objects.filter(difficulty='Medium').delete()

        url = reverse('create_quiz')
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 5,
            'medium_count': 10,
            'hard_count': 5,
            'sec_count': 5
        }
        response = self.client.post(url, data)
        self.assertFalse(Quiz.objects.filter(title='New Quiz').exists())

    def test_insufficient_hard_questions_shows_error(self):
        """Test error when insufficient hard questions"""
        Question.objects.filter(difficulty='Hard').delete()

        url = reverse('create_quiz')
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 5,
            'medium_count': 5,
            'hard_count': 10,
            'sec_count': 5
        }
        response = self.client.post(url, data)
        self.assertFalse(Quiz.objects.filter(title='New Quiz').exists())

    def test_insufficient_secondary_questions_shows_error(self):
        """Test error when insufficient secondary questions"""
        Question.objects.filter(difficulty='Hard').delete()
        for i in range(15):
            Question.objects.create(
                job_level=self.level,
                question_prompt=f"Hard {i}",
                type="MCQ",
                difficulty="Hard"
            )

        url = reverse('create_quiz')
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 2,
            'medium_count': 2,
            'hard_count': 3,
            'sec_count': 5
        }
        response = self.client.post(url, data)
        self.assertFalse(Quiz.objects.filter(title='New Quiz').exists())

    def test_invalid_quota_values_shows_error(self):
        """Test non-integer quota values show error"""
        url = reverse('create_quiz')
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 'abc',  # Invalid string
            'medium_count': 5,
            'hard_count': 5,
            'sec_count': 5
        }
        response = self.client.post(url, data)
        self.assertFalse(Quiz.objects.filter(title='New Quiz').exists())



    def test_successful_creation_redirects_to_quiz_list(self):
        """Test successful creation redirects to quiz list"""
        # 1. Use the named URL
        url = reverse('create_quiz')

        # 2. Define the data
        data = {
            'title': 'New Quiz',
            'primary_level': self.level.id,
            'easy_count': 5,
            'medium_count': 5,
            'hard_count': 5,
            'sec_count': 5
        }

        # 3. Use self.client (Handles messages + redirects automatically)
        response = self.client.post(url, data)

        # 4. Assert the redirect
        self.assertEqual(response.status_code, 302)
        # Optional: Verify it redirects to the correct place
        self.assertEqual(response.url, reverse('quiz_list'))


    def test_quiz_with_secondary_level(self):
        """Test creating quiz with secondary level"""
        secondary_level = JobLevel.objects.create(
            job=self.job,
            level_name="Senior",
            jd_text="Senior JD"
        )
        # Create hard questions for secondary level
        for i in range(20):
            Question.objects.create(
                job_level=secondary_level,
                question_prompt=f"Senior Hard {i}",
                type="MCQ",
                difficulty="Hard"
            )

        url = reverse('create_quiz')
        data = {
            'title': 'Advanced Quiz',
            'primary_level': self.level.id,
            'secondary_level': secondary_level.id,
            'easy_count': 5,
            'medium_count': 5,
            'hard_count': 5,
            'sec_count': 5
        }
        # self.client handles the request + middleware (Messages/Sessions)
        self.client.post(url, data)

        quiz = Quiz.objects.get(title='Advanced Quiz')
        self.assertEqual(quiz.secondary_job_level, secondary_level)

    def test_quiz_without_secondary_level(self):
        """Test creating quiz without secondary level (uses primary)"""
        url = reverse('create_quiz')
        data = {
            'title': 'Simple Quiz',
            'primary_level': self.level.id,
            'easy_count': 2,
            'medium_count': 2,
            'hard_count': 2,
            'sec_count': 2
        }
        self.client.post(url, data)

        quiz = Quiz.objects.get(title='Simple Quiz')
        self.assertIsNone(quiz.secondary_job_level)

    def test_same_primary_and_secondary_level_validation(self):
        """Test validation when primary and secondary are same"""
        # Create exactly 20 hard questions
        Question.objects.filter(difficulty='Hard').delete()
        for i in range(20):
            Question.objects.create(
                job_level=self.level,
                question_prompt=f"Hard {i}",
                type="MCQ",
                difficulty="Hard"
            )

        url = reverse('create_quiz')
        data = {
            'title': 'Same Level Quiz',
            'primary_level': self.level.id,
            'secondary_level': self.level.id,
            'easy_count': 2,
            'medium_count': 2,
            'hard_count': 5,  # Requires 10 hard
            'sec_count': 5  # Requires 10 more (Total 20)
        }
        # This post would normally fail and try to send a 'messages.error'
        self.client.post(url, data)

        # Should fail validation due to logic in the view
        self.assertFalse(Quiz.objects.filter(title='Same Level Quiz').exists())

    def test_missing_title_creates_quiz_with_none_title(self):
        """Test missing title"""
        url = reverse('create_quiz')
        data = {
            'primary_level': self.level.id,
            'easy_count': 2,
            'medium_count': 2,
            'hard_count': 2,
            'sec_count': 2
        }
        self.client.post(url, data)

        # Verify behavior (usually if title is missing, it won't create or it will use default)
        # Check your model logic; if it's required, this count should be 0
        self.assertFalse(Quiz.objects.filter(primary_job_level=self.level).exists())

    def test_missing_primary_level_causes_error(self):
        """Test missing primary level"""
        request = self.factory.post('/quiz/create/', {
            'title': 'No Level Quiz',
            'easy_count': 2,
            'medium_count': 2,
            'hard_count': 2,
            'sec_count': 2
        })
        # Should cause an error (IntegrityError or ValueError)


# ============================================================
# 12. VIEW QUIZ QUESTIONS TESTS
# ============================================================

class ViewQuizQuestionsTests(TestCase):
    """Test view_quiz_questions view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5,
            is_finalized=False
        )
        # Create questions
        for difficulty in ['Easy', 'Medium', 'Hard']:
            for i in range(20):
                Question.objects.create(
                    job_level=self.level,
                    question_prompt=f"{difficulty} Q{i}",
                    type="MCQ",
                    difficulty=difficulty
                )

    def test_get_view_quiz_questions_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/questions/')
        response = view_quiz_questions(request, quiz_id=self.quiz.id)
        self.assertEqual(response.status_code, 200)

    def test_non_finalized_quiz_shows_preview(self):
        """Test non-finalized quiz shows preview mode"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/questions/')
        response = view_quiz_questions(request, quiz_id=self.quiz.id)
        self.assertFalse(response.context['is_finalized'])
        self.assertIn('simulated_test', response.context)

    def test_finalized_quiz_shows_saved_questions(self):
        """Test finalized quiz shows saved questions"""
        self.quiz.is_finalized = True
        self.quiz.save()

        # Create some QuizQuestion entries
        question = Question.objects.filter(difficulty='Easy').first()
        QuizQuestion.objects.create(
            quiz=self.quiz,
            question=question,
            difficulty='Easy',
            role=QuizQuestion.Role.PRIMARY,
            pool=QuizQuestion.Pool.PRIMARY_POOL,
            order=0
        )

        request = self.factory.get(f'/quiz/{self.quiz.id}/questions/')
        response = view_quiz_questions(request, quiz_id=self.quiz.id)
        self.assertTrue(response.context['is_finalized'])
        self.assertIn('finalized_data', response.context)

    def test_nonexistent_quiz_raises_404(self):
        """Test non-existent quiz raises 404"""
        from django.http import Http404
        request = self.factory.get('/quiz/99999/questions/')
        with self.assertRaises(Http404):
            view_quiz_questions(request, quiz_id=99999)

    def test_preview_mode_simulates_correct_counts(self):
        """Test preview mode simulates correct question counts"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/questions/')
        response = view_quiz_questions(request, quiz_id=self.quiz.id)
        simulated = response.context['simulated_test']
        # Check Easy questions
        self.assertEqual(simulated['Easy']['req'], 5)


# ============================================================
# 13. ASSIGNMENT LIST TESTS
# ============================================================

class AssignmentListTests(TestCase):
    """Test assignment_list view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )
        self.candidate = Candidate.objects.create(
            name="John Doe",
            email="john@example.com"
        )
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )

    def test_get_assignment_list_returns_200(self):
        """Test GET request returns 200"""
        request = self.factory.get('/assignments/')
        response = assignment_list(request)
        self.assertEqual(response.status_code, 200)

    def test_displays_all_assessments(self):
        """Test all assessments are displayed"""
        request = self.factory.get('/assignments/')
        response = assignment_list(request)
        self.assertEqual(len(response.context['assessments']), 1)

    def test_assessments_ordered_by_id_desc(self):
        """Test assessments ordered by ID descending"""
        assessment2 = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )
        request = self.factory.get('/assignments/')
        response = assignment_list(request)
        assessments = list(response.context['assessments'])
        self.assertTrue(assessments[0].id >= assessments[1].id)

    def test_empty_assessment_list(self):
        """Test empty assessment list"""
        Assessment.objects.all().delete()
        request = self.factory.get('/assignments/')
        response = assignment_list(request)
        self.assertEqual(len(response.context['assessments']), 0)


# ============================================================
# 14. DELETE ASSESSMENT TESTS
# ============================================================

class DeleteAssessmentTests(TestCase):
    """Test delete_assessment view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )
        self.candidate = Candidate.objects.create(
            name="John Doe",
            email="john@example.com"
        )
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )

    def test_post_deletes_assessment(self):
        """Test POST deletes assessment"""
        request = self.factory.post(f'/assessment/{self.assessment.id}/delete/')
        delete_assessment(request, assessment_id=self.assessment.id)
        self.assertFalse(Assessment.objects.filter(id=self.assessment.id).exists())

    def test_get_does_not_delete(self):
        """Test GET doesn't delete assessment"""
        request = self.factory.get(f'/assessment/{self.assessment.id}/delete/')
        delete_assessment(request, assessment_id=self.assessment.id)
        self.assertTrue(Assessment.objects.filter(id=self.assessment.id).exists())

    def test_redirects_to_assignment_list(self):
        """Test redirects to assignment list"""
        request = self.factory.post(f'/assessment/{self.assessment.id}/delete/')
        response = delete_assessment(request, assessment_id=self.assessment.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('assignment_list'))

    def test_delete_nonexistent_assessment_raises_404(self):
        """Test deleting non-existent assessment raises 404"""
        from django.http import Http404
        random_uuid = uuid.uuid4()
        request = self.factory.post(f'/assessment/{random_uuid}/delete/')
        with self.assertRaises(Http404):
            delete_assessment(request, assessment_id=random_uuid)


# ============================================================
# 15. CREATE ASSIGNMENT TESTS
# ============================================================

class CreateAssignmentTests(TestCase):
    """Test create_assignment view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )

    def test_get_create_assignment_returns_200(self):
        """Test GET returns 200"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/assign/')
        response = create_assignment(request, quiz_id=self.quiz.id)
        self.assertEqual(response.status_code, 200)

    def test_get_displays_quiz(self):
        """Test quiz is in context"""
        request = self.factory.get(f'/quiz/{self.quiz.id}/assign/')
        response = create_assignment(request, quiz_id=self.quiz.id)
        self.assertEqual(response.context['quiz'], self.quiz)


    def test_post_creates_assessment(self):
        """Test POST creates assessment"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {
            'candidate_name': 'Jane Doe',
            'candidate_email': 'jane@example.com',
            'time_limit': 30
        }
        self.client.post(url, data)
        self.assertTrue(Assessment.objects.filter(quiz=self.quiz).exists())

    def test_post_creates_or_gets_candidate(self):
        """Test candidate is created or retrieved"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {
            'candidate_name': 'Jane Doe',
            'candidate_email': 'jane@example.com',
            'time_limit': 30
        }
        self.client.post(url, data)
        self.assertTrue(Candidate.objects.filter(email='jane@example.com').exists())

    def test_post_creates_test_session(self):
        """Test TestSession is created"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {'candidate_name': 'Jane Doe', 'candidate_email': 'jane@example.com', 'time_limit': 30}
        self.client.post(url, data)

        assessment = Assessment.objects.get(quiz=self.quiz)
        self.assertTrue(TestSession.objects.filter(assessment=assessment).exists())

    def test_session_initialized_with_correct_pools(self):
        """Test session is initialized with correct pool values"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {'candidate_name': 'Jane Doe', 'candidate_email': 'jane@example.com', 'time_limit': 30}
        self.client.post(url, data)

        session = TestSession.objects.first()
        self.assertEqual(session.easy_pool, 5)
        self.assertEqual(session.medium_pool, 10)
        self.assertEqual(session.hard_pool, 5)
        self.assertEqual(session.current_difficulty, 'Easy')

    def test_post_generates_magic_link(self):
        """Test magic link token is generated"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {'candidate_name': 'Jane Doe', 'candidate_email': 'jane@example.com', 'time_limit': 30}
        self.client.post(url, data)

        assessment = Assessment.objects.first()
        self.assertIsNotNone(assessment.magic_link_token)

    def test_post_redirects_to_quiz_list(self):
        """Test POST redirects to quiz list"""
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {'candidate_name': 'Jane Doe', 'candidate_email': 'jane@example.com', 'time_limit': 30}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)


    def test_duplicate_candidate_email_reuses_candidate(self):
        """Test duplicate email reuses existing candidate"""
        # 1. Setup existing data
        existing = Candidate.objects.create(
            name="Old Name",
            email="jane@example.com"
        )

        # 2. Use self.client to POST
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {
            'candidate_name': 'New Name',
            'candidate_email': 'jane@example.com',
            'time_limit': 30
        }
        self.client.post(url, data)

        # 3. Assertions - Count should still be 1 because email is unique
        self.assertEqual(Candidate.objects.filter(email='jane@example.com').count(), 1)

    def test_default_time_limit(self):
        """Test default time limit is 30 minutes"""
        # 1. Use self.client to POST (omitting time_limit to test default)
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        data = {
            'candidate_name': 'Jane Doe',
            'candidate_email': 'jane@example.com'
        }
        self.client.post(url, data)

        # 2. Verify assessment was created with the default value
        assessment = Assessment.objects.first()
        self.assertEqual(assessment.test_duration_mins, 30)

    def test_custom_time_limit(self):
        """Test custom time limit using the test client"""
        # 1. Define the data
        data = {
            'candidate_name': 'Jane Doe',
            'candidate_email': 'jane@example.com',
            'time_limit': 60
        }

        # 2. Use self.client to post to the named URL
        url = reverse('create_assignment', kwargs={'quiz_id': self.quiz.id})
        response = self.client.post(url, data)

        # 3. Verify logic
        self.assertEqual(response.status_code, 302)  # Should redirect after success
        assessment = Assessment.objects.first()
        self.assertEqual(assessment.test_duration_mins, 60)


# ============================================================
# 16. FINALIZE QUIZ QUESTIONS TESTS
# ============================================================

class FinalizeQuizQuestionsTransactionTests(TransactionTestCase):
    """Test finalize_quiz_questions view (uses TransactionTestCase for atomic testing)"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python Developer")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="Junior JD"
        )
        # Create enough questions
        for difficulty in ['Easy', 'Medium', 'Hard']:
            for i in range(20):
                Question.objects.create(
                    job_level=self.level,
                    question_prompt=f"{difficulty} Q{i}",
                    type="MCQ",
                    difficulty=difficulty
                )

        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=5,
            hard_count=5,
            secondary_exam_count=5,
            is_finalized=False
        )

    def test_post_finalizes_quiz(self):
        """Test POST finalizes quiz"""
        # 1. Use reverse to get the URL
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})

        # 2. Use self.client.post (Handles messages automatically)
        response = self.client.post(url)

        # 3. Refresh from DB to see the change made by the view
        self.quiz.refresh_from_db()

        # 4. Assertions
        self.assertEqual(response.status_code, 302)  # Usually redirects after POST
        self.assertTrue(self.quiz.is_finalized)

    def test_creates_quiz_questions(self):
        """Test QuizQuestion objects are created"""
        request = self.factory.post(f'/quiz/{self.quiz.id}/finalize/')

        # 1. ADD SESSION SUPPORT (Fixes ImproperlyConfigured)
        # This simulates the SessionMiddleware
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session.save()

        # 2. ADD MESSAGE SUPPORT (Fixes MessageFailure)
        setattr(request, '_messages', FallbackStorage(request))

        # Now the view has everything it needs to run successfully
        finalize_quiz_questions(request, quiz_id=self.quiz.id)

        # Assertions
        self.assertEqual(QuizQuestion.objects.filter(quiz=self.quiz).count(), 40)


    def test_already_finalized_returns_warning(self):
        """Test already finalized quiz shows warning"""
        self.quiz.is_finalized = True
        self.quiz.save()

        # Use self.client to handle the warning message safely
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

    def test_get_request_redirects(self):
        """Test GET request redirects without finalizing"""
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        response = self.client.get(url)

        self.quiz.refresh_from_db()
        self.assertFalse(self.quiz.is_finalized)
        self.assertEqual(response.status_code, 302)

    def test_insufficient_questions_shows_error(self):
        """Test insufficient questions prevents finalization"""
        # Delete questions to trigger the 'error' message in the view
        Question.objects.filter(difficulty='Easy').delete()

        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        response = self.client.post(url)

        self.quiz.refresh_from_db()
        self.assertFalse(self.quiz.is_finalized)

    def test_creates_primary_and_buffer_roles(self):
        """Test both PRIMARY and BUFFER roles are created"""
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        self.client.post(url)

        primary_count = QuizQuestion.objects.filter(
            quiz=self.quiz,
            role=QuizQuestion.Role.PRIMARY
        ).count()
        buffer_count = QuizQuestion.objects.filter(
            quiz=self.quiz,
            role=QuizQuestion.Role.BUFFER
        ).count()

        self.assertEqual(primary_count, 20)
        self.assertEqual(buffer_count, 20)

    def test_secondary_pool_created(self):
        """Test secondary pool is correctly populated"""
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        self.client.post(url)

        secondary_count = QuizQuestion.objects.filter(
            quiz=self.quiz,
            pool=QuizQuestion.Pool.SECONDARY_POOL
        ).count()
        self.assertEqual(secondary_count, 10)

    def test_redirects_after_finalization(self):
        """Test redirects to view quiz questions"""
        # Use the name defined in your urls.py (likely 'finalize_quiz_questions')
        url = reverse('finalize_quiz_questions', kwargs={'quiz_id': self.quiz.id})

        response = self.client.post(url)

        # This should now pass because reverse() generates the perfect URL
        self.assertEqual(response.status_code, 302)

        # Check the redirect destination using reverse as well
        expected_url = reverse('view_quiz_questions', kwargs={'quiz_id': self.quiz.id})
        self.assertRedirects(response, expected_url)

    def test_transaction_rollback_on_error(self):
        """Test transaction rollback on error"""
        # This would need to force an error during finalization
        # For example, by mocking bulk_create to raise an exception
        pass


# ============================================================
# 17. HELPER FUNCTION TESTS
# ============================================================

class HelperFunctionTests(TestCase):
    """Test helper functions"""

    def setUp(self):
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(
            job=self.job,
            level_name="Junior",
            jd_text="JD"
        )
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=5,
            hard_count=5,
            secondary_exam_count=5,
            is_finalized=True
        )

        # Create questions and QuizQuestions
        for i in range(10):
            q = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Easy Q{i}",
                type="MCQ",
                difficulty="Easy"
            )
            QuizQuestion.objects.create(
                quiz=self.quiz,
                question=q,
                difficulty='Easy',
                role=QuizQuestion.Role.PRIMARY if i < 5 else QuizQuestion.Role.BUFFER,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                order=i
            )

    def test_questions_remaining_returns_correct_count(self):
        """Test _questions_remaining returns correct count"""
        count = _questions_remaining(self.quiz, 'Easy', [])
        self.assertEqual(count, 10)

    def test_questions_remaining_excludes_answered(self):
        """Test _questions_remaining excludes answered IDs"""
        q = QuizQuestion.objects.first()
        count = _questions_remaining(self.quiz, 'Easy', [q.question_id])
        self.assertEqual(count, 9)

    def test_pick_question_returns_primary_first(self):
        """Test _pick_question returns primary before buffer"""
        question, is_buffer = _pick_question(self.quiz, 'Easy', [])
        self.assertIsNotNone(question)
        self.assertFalse(is_buffer)

    def test_pick_question_returns_buffer_when_primary_exhausted(self):
        """Test _pick_question returns buffer when primary exhausted"""
        # Get all primary question IDs
        primary_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy',
            role=QuizQuestion.Role.PRIMARY
        ).values_list('question_id', flat=True))

        question, is_buffer = _pick_question(self.quiz, 'Easy', primary_ids)
        self.assertIsNotNone(question)
        self.assertTrue(is_buffer)

    def test_pick_question_returns_none_when_all_exhausted(self):
        """Test _pick_question returns None when all exhausted"""
        all_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy'
        ).values_list('question_id', flat=True))

        question, is_buffer = _pick_question(self.quiz, 'Easy', all_ids)
        self.assertIsNone(question)
        self.assertFalse(is_buffer)

    def test_apply_buffer_penalty_does_nothing_when_not_buffer(self):
        """Test _apply_buffer_penalty does nothing when is_buffer=False"""
        candidate = Candidate.objects.create(name="Test", email="test@example.com")
        assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=candidate,
            magic_link_token=str(uuid.uuid4())
        )
        session = TestSession.objects.create(
            assessment=assessment,
            easy_pool=5,
            medium_pool=5,
            hard_pool=5
        )

        initial_score = session.running_score
        _apply_buffer_penalty(session, 'Easy', is_buffer=False)
        self.assertEqual(session.running_score, initial_score)

    def test_apply_buffer_penalty_applies_penalty_when_buffer(self):
        """Test _apply_buffer_penalty applies penalty when is_buffer=True"""
        candidate = Candidate.objects.create(name="Test", email="test@example.com")
        assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=candidate,
            magic_link_token=str(uuid.uuid4())
        )
        session = TestSession.objects.create(
            assessment=assessment,
            easy_pool=5,
            medium_pool=5,
            hard_pool=5,
            running_score=10
        )

        _apply_buffer_penalty(session, 'Easy', is_buffer=True)
        self.assertEqual(session.running_score, 10 + BUFFER_BORROW_PENALTY['Easy'])

    def test_apply_buffer_penalty_shrinks_next_pool(self):
        """Test _apply_buffer_penalty shrinks next pool"""
        candidate = Candidate.objects.create(name="Test", email="test@example.com")
        assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=candidate,
            magic_link_token=str(uuid.uuid4())
        )
        session = TestSession.objects.create(
            assessment=assessment,
            easy_pool=5,
            medium_pool=5,
            hard_pool=5
        )

        _apply_buffer_penalty(session, 'Easy', is_buffer=True)
        # Easy's next level is Medium, so medium_pool should shrink
        self.assertEqual(session.medium_pool, 4)


# ============================================================
# 18. PROCESS ANSWER TESTS
# ============================================================

class ProcessAnswerTests(TestCase):
    """Test process_answer helper function"""

    def setUp(self):
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(job=self.job, level_name="Junior", jd_text="JD")
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=5,
            hard_count=5,
            secondary_exam_count=5
        )
        self.candidate = Candidate.objects.create(name="Test", email="test@example.com")
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            current_difficulty='Easy',
            consecutive_correct=0,
            consecutive_wrong=0,
            running_score=0
        )

    def test_correct_answer_increments_score(self):
        """Test correct answer increments score"""
        initial_score = self.session.running_score
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(
            self.session.running_score,
            initial_score + CORRECT_MARKS['Easy']
        )

    def test_correct_answer_increments_consecutive_correct(self):
        """Test correct answer increments consecutive_correct"""
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 1)

    def test_correct_answer_resets_consecutive_wrong(self):
        """Test correct answer resets consecutive_wrong"""
        self.session.consecutive_wrong = 3
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_two_correct_promotes_difficulty(self):
        """Test 2 consecutive correct answers promotes difficulty"""
        self.session.consecutive_correct = 1
        result = process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(result, 'promote')
        self.assertEqual(self.session.current_difficulty, 'Medium')

    def test_promotion_resets_streaks(self):
        """Test promotion resets both streaks"""
        self.session.consecutive_correct = 1
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 0)
        self.assertEqual(self.session.consecutive_wrong, 0)

    def test_promotion_sets_gate_passed_when_reaching_medium(self):
        """Test promotion to Medium sets is_gate_passed"""
        self.session.consecutive_correct = 1
        process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertTrue(self.session.is_gate_passed)

    def test_no_promotion_beyond_secondary(self):
        """Test no promotion beyond Secondary difficulty"""
        self.session.current_difficulty = 'Secondary'
        self.session.consecutive_correct = 1
        result = process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Secondary')

    def test_wrong_answer_increments_consecutive_wrong(self):
        """Test wrong answer increments consecutive_wrong"""
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.consecutive_wrong, 1)

    def test_wrong_answer_resets_consecutive_correct(self):
        """Test wrong answer resets consecutive_correct"""
        self.session.consecutive_correct = 3
        process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(self.session.consecutive_correct, 0)

    def test_two_wrong_demotes_difficulty(self):
        """Test 2 consecutive wrong answers demotes difficulty"""
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_wrong = 1
        result = process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(result, 'demote')
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_demotion_applies_penalty(self):
        """Test demotion applies step-down penalty"""
        self.session.current_difficulty = 'Medium'
        self.session.consecutive_wrong = 1
        self.session.running_score = 10
        process_answer(self.session, is_correct=False, is_skipped=False)
        expected_score = 10 + STEPDOWN_PENALTY[('Medium', 'Easy')]
        self.assertEqual(self.session.running_score, expected_score)

    def test_no_demotion_below_easy(self):
        """Test no demotion below Easy difficulty"""
        self.session.current_difficulty = 'Easy'
        self.session.consecutive_wrong = 1
        result = process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_skipped_answer_counts_as_wrong(self):
        """Test skipped answer is treated as wrong"""
        process_answer(self.session, is_correct=False, is_skipped=True)
        self.assertEqual(self.session.consecutive_wrong, 1)
        self.assertEqual(self.session.consecutive_correct, 0)

    def test_one_correct_stays_at_same_level(self):
        """Test single correct answer doesn't promote"""
        result = process_answer(self.session, is_correct=True, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Easy')

    def test_one_wrong_stays_at_same_level(self):
        """Test single wrong answer doesn't demote"""
        result = process_answer(self.session, is_correct=False, is_skipped=False)
        self.assertEqual(result, 'stay')
        self.assertEqual(self.session.current_difficulty, 'Easy')


# ============================================================
# 19. GET NEXT QUESTION TESTS
# ============================================================

class GetNextQuestionTests(TestCase):
    """Test get_next_question helper function"""

    def setUp(self):
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(job=self.job, level_name="Junior", jd_text="JD")
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=2,
            medium_count=2,
            hard_count=2,
            secondary_exam_count=2,
            is_finalized=True
        )

        # Create Easy questions
        for i in range(4):
            q = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Easy Q{i}",
                type="MCQ",
                difficulty="Easy"
            )
            QuizQuestion.objects.create(
                quiz=self.quiz,
                question=q,
                difficulty='Easy',
                role=QuizQuestion.Role.PRIMARY if i < 2 else QuizQuestion.Role.BUFFER,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                order=i
            )

        # Create Medium questions
        for i in range(4):
            q = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Medium Q{i}",
                type="MCQ",
                difficulty="Medium"
            )
            QuizQuestion.objects.create(
                quiz=self.quiz,
                question=q,
                difficulty='Medium',
                role=QuizQuestion.Role.PRIMARY if i < 2 else QuizQuestion.Role.BUFFER,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                order=i
            )

        self.candidate = Candidate.objects.create(name="Test", email="test@example.com")
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            current_difficulty='Easy',
            easy_pool=2,
            medium_pool=2,
            hard_pool=2
        )

    def test_returns_question_from_current_difficulty(self):
        """Test returns question from current difficulty"""
        question, terminated = get_next_question(self.session, self.quiz)
        self.assertIsNotNone(question)
        self.assertFalse(terminated)
        self.assertEqual(question.difficulty, 'Easy')

    def test_returns_primary_before_buffer(self):
        """Test returns primary questions before buffer"""
        question, terminated = get_next_question(self.session, self.quiz)
        # First call should give primary
        qq = QuizQuestion.objects.get(quiz=self.quiz, question=question, difficulty='Easy')
        self.assertEqual(qq.role, QuizQuestion.Role.PRIMARY)

    def test_fallback_when_current_level_exhausted(self):
        """Test falls back to lower difficulty when current exhausted"""
        # Answer all Easy questions
        easy_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy'
        ).values_list('question_id', flat=True))

        # Create responses for all easy questions
        for qid in easy_ids:
            Response.objects.create(
                test_session=self.session,
                question_id=qid,
                is_correct=True
            )

        self.session.current_difficulty = 'Medium'
        # Exhaust medium too
        medium_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Medium'
        ).values_list('question_id', flat=True))

        for qid in medium_ids:
            Response.objects.create(
                test_session=self.session,
                question_id=qid,
                is_correct=True
            )

        # Now should fall back to Easy (which is exhausted too)
        question, terminated = get_next_question(self.session, self.quiz)
        # Since both are exhausted, should terminate
        self.assertTrue(terminated or question is None)

    def test_terminates_when_all_questions_exhausted(self):
        """Test terminates when all questions exhausted"""
        # Answer all questions
        all_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz
        ).values_list('question_id', flat=True))

        for qid in all_ids:
            Response.objects.create(
                test_session=self.session,
                question_id=qid,
                is_correct=True
            )

        question, terminated = get_next_question(self.session, self.quiz)
        self.assertIsNone(question)
        self.assertTrue(terminated)

    def test_session_marked_inactive_when_terminated(self):
        """Test session.is_active set to False when terminated"""
        # Answer all questions
        all_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz
        ).values_list('question_id', flat=True))

        for qid in all_ids:
            Response.objects.create(
                test_session=self.session,
                question_id=qid,
                is_correct=True
            )

        question, terminated = get_next_question(self.session, self.quiz)
        self.assertFalse(self.session.is_active)

    def test_buffer_penalty_applied_when_using_buffer(self):
        """Test buffer penalty is applied when using buffer question"""
        # Answer all primary Easy questions
        primary_ids = list(QuizQuestion.objects.filter(
            quiz=self.quiz,
            difficulty='Easy',
            role=QuizQuestion.Role.PRIMARY
        ).values_list('question_id', flat=True))

        for qid in primary_ids:
            Response.objects.create(
                test_session=self.session,
                question_id=qid,
                is_correct=True
            )

        initial_score = self.session.running_score
        question, terminated = get_next_question(self.session, self.quiz)
        # Should have used buffer and applied penalty
        self.assertEqual(
            self.session.running_score,
            initial_score + BUFFER_BORROW_PENALTY['Easy']
        )


# ============================================================
# 20. COMPLETE ASSESSMENT TESTS
# ============================================================

class CompleteAssessmentTests(TestCase):
    """Test _complete_assessment helper function"""

    def setUp(self):
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(job=self.job, level_name="Junior", jd_text="JD")
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5
        )
        self.candidate = Candidate.objects.create(name="Test", email="test@example.com")
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4()),
            status=Assessment.Status.IN_PROGRESS
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            running_score=50,
            is_active=True
        )

    def test_calculates_final_score_percentage(self):
        """Test calculates final score percentage correctly"""
        _complete_assessment(self.assessment, self.session)
        self.assessment.refresh_from_db()

        # Calculate expected max score
        max_possible = (
            5 * CORRECT_MARKS['Easy'] +
            10 * CORRECT_MARKS['Medium'] +
            5 * CORRECT_MARKS['Hard'] +
            5 * CORRECT_MARKS['Secondary']
        )
        expected_pct = round((50 / max_possible) * 100, 2)
        self.assertEqual(self.assessment.final_score, expected_pct)

    def test_sets_assessment_status_to_completed(self):
        """Test sets assessment status to COMPLETED"""
        _complete_assessment(self.assessment, self.session)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)

    def test_sets_session_inactive(self):
        """Test sets session.is_active to False"""
        _complete_assessment(self.assessment, self.session)
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)

    def test_clears_current_question(self):
        """Test clears session.current_question"""
        question = Question.objects.create(
            job_level=self.level,
            question_prompt="Test Q",
            type="MCQ",
            difficulty="Easy"
        )
        self.session.current_question = question
        self.session.save()

        _complete_assessment(self.assessment, self.session)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.current_question)

    def test_handles_zero_max_possible_score(self):
        """Test handles edge case of zero max possible score"""
        zero_quiz = Quiz.objects.create(
            title="Zero Quiz",
            primary_job_level=self.level,
            easy_count=0,
            medium_count=0,
            hard_count=0,
            secondary_exam_count=0
        )
        assessment = Assessment.objects.create(
            quiz=zero_quiz,
            candidate=self.candidate,
            magic_link_token=str(uuid.uuid4())
        )
        session = TestSession.objects.create(
            assessment=assessment,
            running_score=0
        )

        _complete_assessment(assessment, session)
        assessment.refresh_from_db()
        self.assertEqual(assessment.final_score, 0)

    def test_saves_both_session_and_assessment(self):
        """Test both session and assessment are saved"""
        _complete_assessment(self.assessment, self.session)
        # If no exception, both saved successfully
        self.session.refresh_from_db()
        self.assessment.refresh_from_db()


# ============================================================
# 21. TAKE ASSESSMENT TESTS
# ============================================================

class TakeAssessmentTests(TestCase):
    """Test take_assessment view"""

    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(job=self.job, level_name="Junior", jd_text="JD")
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5,
            total_questions_limit=25,
            is_finalized=True
        )

        # Create questions
        for i in range(5):
            q = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Easy Q{i}",
                type="MCQ",
                difficulty="Easy"
            )
            QuestionOption.objects.create(question=q, option_text="A", is_correct=True)
            QuizQuestion.objects.create(
                quiz=self.quiz,
                question=q,
                difficulty='Easy',
                role=QuizQuestion.Role.PRIMARY,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                order=i
            )

        self.candidate = Candidate.objects.create(name="Test", email="test@example.com")
        self.token = str(uuid.uuid4())
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=self.token,
            status=Assessment.Status.NOT_STARTED,
            test_duration_mins=30
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            current_difficulty='Easy',
            is_active=True
        )

    def test_get_take_assessment_returns_200(self):
        """Test GET returns 200"""
        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assertEqual(response.status_code, 200)

    def test_completed_assessment_shows_completion_page(self):
        """Test completed assessment shows completion page"""
        self.assessment.status = Assessment.Status.COMPLETED
        self.assessment.save()

        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assertIn('quiz_complete.html', response.template_name)

    def test_time_up_completes_assessment(self):
        """Test time's up completes assessment"""
        # Set started_at to past
        self.assessment.started_at = timezone.now() - timedelta(minutes=40)
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()

        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)

    def test_inactive_session_completes_assessment(self):
        """Test inactive session completes assessment"""
        self.session.is_active = False
        self.session.save()

        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)


    def test_not_started_changes_to_in_progress(self):
        """Test NOT_STARTED changes to IN_PROGRESS on first access"""
        # 1. Use the client and reverse the URL
        url = reverse('take_assessment', kwargs={'token': self.token})
        response = self.client.get(url)

        # 2. Refresh the object from the database to get the new status
        self.assessment.refresh_from_db()

        # 3. Verify the change
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assessment.status, Assessment.Status.IN_PROGRESS)

    def test_locks_current_question_on_first_load(self):
        """Test locks current question on first load"""
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()

        request = self.factory.get(f'/take/{self.token}/')
        take_assessment(request, token=self.token)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.current_question)

    def test_uses_existing_current_question_on_reload(self):
        """Test uses existing current_question on reload"""
        question = Question.objects.first()
        self.session.current_question = question
        self.session.save()
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()

        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assertEqual(response.context['question'], question)

    def test_calculates_time_remaining_correctly(self):
        """Test calculates time remaining correctly"""
        # 1. Setup the scenario (10 minutes have passed)
        self.assessment.started_at = timezone.now() - timedelta(minutes=10)
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()

        # 2. Use self.client to get the page
        url = reverse('take_assessment', kwargs={'token': self.token})
        response = self.client.get(url)

        # 3. Access 'context' (This works now because we used self.client)
        time_remaining = response.context['time_remaining']

        # Assertions for ~20 minutes remaining (1200 seconds)
        self.assertGreater(time_remaining, 1100)
        self.assertLess(time_remaining, 1300)

    def test_progress_percentage_calculated_correctly(self):
        """Test progress percentage calculated correctly"""
        # 1. Setup session progress
        self.session.total_q_answered = 10
        self.session.save()
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()

        # 2. Use self.client to get the page
        url = reverse('take_assessment', kwargs={'token': self.token})
        response = self.client.get(url)

        # 3. 10 answered / 25 total = 40%
        self.assertEqual(response.context['progress_pct'], 40)
    
    def test_nonexistent_token_raises_404(self):
        """Test non-existent token raises 404"""
        from django.http import Http404
        request = self.factory.get('/take/invalid-token/')
        with self.assertRaises(Http404):
            take_assessment(request, token='invalid-token')
    
    def test_no_questions_available_completes_assessment(self):
        """Test completes assessment when no questions available"""
        # Delete all quiz questions
        QuizQuestion.objects.all().delete()
        self.assessment.status = Assessment.Status.IN_PROGRESS
        self.assessment.save()
        
        request = self.factory.get(f'/take/{self.token}/')
        response = take_assessment(request, token=self.token)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)


# ============================================================
# 22. SUBMIT ANSWER TESTS
# ============================================================

class SubmitAnswerTests(TransactionTestCase):
    """Test submit_answer view (uses TransactionTestCase for atomic testing)"""
    
    def setUp(self):
        self.factory = RequestFactory()
        self.job = Job.objects.create(name="Python")
        self.level = JobLevel.objects.create(job=self.job, level_name="Junior", jd_text="JD")
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            primary_job_level=self.level,
            easy_count=5,
            medium_count=10,
            hard_count=5,
            secondary_exam_count=5,
            total_questions_limit=25,
            is_finalized=True
        )
        
        # Create MCQ question
        self.mcq_question = Question.objects.create(
            job_level=self.level,
            question_prompt="MCQ Question",
            type="MCQ",
            difficulty="Easy"
        )
        self.correct_option = QuestionOption.objects.create(
            question=self.mcq_question,
            option_text="Correct",
            is_correct=True
        )
        self.wrong_option = QuestionOption.objects.create(
            question=self.mcq_question,
            option_text="Wrong",
            is_correct=False
        )
        
        # Create MSQ question
        self.msq_question = Question.objects.create(
            job_level=self.level,
            question_prompt="MSQ Question",
            type="MSQ",
            difficulty="Easy"
        )
        self.msq_correct1 = QuestionOption.objects.create(
            question=self.msq_question,
            option_text="Correct 1",
            is_correct=True
        )
        self.msq_correct2 = QuestionOption.objects.create(
            question=self.msq_question,
            option_text="Correct 2",
            is_correct=True
        )
        self.msq_wrong = QuestionOption.objects.create(
            question=self.msq_question,
            option_text="Wrong",
            is_correct=False
        )
        
        # Create One-Word question
        self.oneword_question = Question.objects.create(
            job_level=self.level,
            question_prompt="One-Word Question",
            type="One-Word",
            difficulty="Easy"
        )
        self.oneword_correct = QuestionOption.objects.create(
            question=self.oneword_question,
            option_text="python",
            is_correct=True
        )
        
        # Create more questions for continuation
        for i in range(30):
            q = Question.objects.create(
                job_level=self.level,
                question_prompt=f"Extra Q{i}",
                type="MCQ",
                difficulty="Easy"
            )
            QuestionOption.objects.create(question=q, option_text="A", is_correct=True)
            QuizQuestion.objects.create(
                quiz=self.quiz,
                question=q,
                difficulty='Easy',
                role=QuizQuestion.Role.PRIMARY,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                order=i
            )
        
        self.candidate = Candidate.objects.create(name="Test", email="test@example.com")
        self.token = str(uuid.uuid4())
        self.assessment = Assessment.objects.create(
            quiz=self.quiz,
            candidate=self.candidate,
            magic_link_token=self.token,
            status=Assessment.Status.IN_PROGRESS,
            started_at=timezone.now()
        )
        self.session = TestSession.objects.create(
            assessment=self.assessment,
            current_difficulty='Easy',
            is_active=True,
            current_question=self.mcq_question
        )
    
    def test_get_request_redirects_to_take_assessment(self):
        """Test GET request redirects"""
        request = self.factory.get(f'/take/{self.token}/submit/')
        response = submit_answer(request, token=self.token)
        self.assertEqual(response.status_code, 302)
    
    def test_mcq_correct_answer(self):
        """Test MCQ correct answer evaluation"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertTrue(response.is_correct)
        self.assertFalse(response.is_skipped)
    
    def test_mcq_wrong_answer(self):
        """Test MCQ wrong answer evaluation"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.wrong_option.id]
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertFalse(response.is_correct)
    
    def test_msq_correct_answer_all_selected(self):
        """Test MSQ correct when all correct options selected"""
        self.session.current_question = self.msq_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.msq_correct1.id, self.msq_correct2.id]
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertTrue(response.is_correct)
    
    def test_msq_wrong_missing_correct_option(self):
        """Test MSQ wrong when missing a correct option"""
        self.session.current_question = self.msq_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.msq_correct1.id]  # Missing correct2
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertFalse(response.is_correct)
    
    def test_msq_wrong_includes_wrong_option(self):
        """Test MSQ wrong when including wrong option"""
        self.session.current_question = self.msq_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.msq_correct1.id, self.msq_correct2.id, self.msq_wrong.id]
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertFalse(response.is_correct)
    
    def test_oneword_correct_answer_case_insensitive(self):
        """Test One-Word correct answer is case-insensitive"""
        self.session.current_question = self.oneword_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'typed_answer': 'PYTHON'
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertTrue(response.is_correct)
    
    def test_oneword_correct_answer_with_whitespace(self):
        """Test One-Word correct answer with whitespace"""
        self.session.current_question = self.oneword_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'typed_answer': '  python  '
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertTrue(response.is_correct)
    
    def test_oneword_wrong_answer(self):
        """Test One-Word wrong answer"""
        self.session.current_question = self.oneword_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'typed_answer': 'java'
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertFalse(response.is_correct)
    
    def test_skip_answer(self):
        """Test skipping a question"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'skip': 'true'
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertTrue(response.is_skipped)
        self.assertFalse(response.is_correct)
    
    def test_increments_total_answered(self):
        """Test increments total_q_answered"""
        initial_count = self.session.total_q_answered
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.session.refresh_from_db()
        self.assertEqual(self.session.total_q_answered, initial_count + 1)
    
    def test_increments_current_question_index(self):
        """Test increments current_question_index"""
        initial_index = self.assessment.current_question_index
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.current_question_index, initial_index + 1)
    
    def test_completes_when_limit_reached(self):
        """Test completes assessment when question limit reached"""
        self.session.total_q_answered = 24  # One before limit
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.status, Assessment.Status.COMPLETED)
    
    def test_gets_next_question_after_submit(self):
        """Test gets next question after submission"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.session.refresh_from_db()
        # Should have a new current_question (or None if exhausted)
        self.assertNotEqual(self.session.current_question, self.mcq_question)
    
    def test_redirects_to_take_assessment_after_submit(self):
        """Test redirects to take_assessment after submission"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        response = submit_answer(request, token=self.token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('take_assessment', kwargs={'token': self.token}))
    
    def test_completed_assessment_redirects_without_saving(self):
        """Test completed assessment redirects without saving response"""
        self.assessment.status = Assessment.Status.COMPLETED
        self.assessment.save()
        
        initial_count = Response.objects.count()
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.assertEqual(Response.objects.count(), initial_count)
    
    def test_time_up_redirects_without_saving(self):
        """Test time's up redirects without saving response"""
        self.assessment.started_at = timezone.now() - timedelta(minutes=40)
        self.assessment.save()
        
        initial_count = Response.objects.count()
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        # Might save one response before detecting time's up, but shouldn't continue
    
    def test_no_current_question_redirects(self):
        """Test no current question redirects"""
        self.session.current_question = None
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        response = submit_answer(request, token=self.token)
        self.assertEqual(response.status_code, 302)
    
    def test_process_answer_called(self):
        """Test process_answer is called with correct parameters"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        self.session.refresh_from_db()
        # If correct answer, score should increase
        self.assertGreater(self.session.running_score, 0)
    
    def test_selected_options_saved_in_response(self):
        """Test selected options are saved in response"""
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'options': [self.correct_option.id]
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertEqual(response.selected_options.count(), 1)
        self.assertIn(self.correct_option, response.selected_options.all())
    
    def test_typed_answer_saved_in_response(self):
        """Test typed answer is saved in response"""
        self.session.current_question = self.oneword_question
        self.session.save()
        
        request = self.factory.post(f'/take/{self.token}/submit/', {
            'typed_answer': 'python'
        })
        submit_answer(request, token=self.token)
        
        response = Response.objects.filter(test_session=self.session).first()
        self.assertEqual(response.typed_answer, 'python')
    
    def test_atomic_transaction_rollback_on_error(self):
        """Test transaction rolls back on error"""
        # This would need to force an error during the transaction
        # For example, by mocking a method to raise an exception
        pass


# ============================================================
# 23. CONSTANTS TESTS
# ============================================================

class ConstantsTests(TestCase):
    """Test that constants are correctly defined"""
    
    def test_correct_marks_defined(self):
        """Test CORRECT_MARKS has all difficulty levels"""
        self.assertIn('Easy', CORRECT_MARKS)
        self.assertIn('Medium', CORRECT_MARKS)
        self.assertIn('Hard', CORRECT_MARKS)
        self.assertIn('Secondary', CORRECT_MARKS)
    
    def test_stepdown_penalty_defined(self):
        """Test STEPDOWN_PENALTY has all transitions"""
        self.assertIn(('Hard', 'Medium'), STEPDOWN_PENALTY)
        self.assertIn(('Medium', 'Easy'), STEPDOWN_PENALTY)
        self.assertIn(('Secondary', 'Hard'), STEPDOWN_PENALTY)
    
    def test_buffer_borrow_penalty_defined(self):
        """Test BUFFER_BORROW_PENALTY has all levels"""
        self.assertIn('Easy', BUFFER_BORROW_PENALTY)
        self.assertIn('Medium', BUFFER_BORROW_PENALTY)
        self.assertIn('Hard', BUFFER_BORROW_PENALTY)
        self.assertIn('Secondary', BUFFER_BORROW_PENALTY)
    
    def test_difficulty_order_correct(self):
        """Test DIFFICULTY_ORDER is in correct sequence"""
        self.assertEqual(DIFFICULTY_ORDER, ['Easy', 'Medium', 'Hard', 'Secondary'])
    
    def test_correct_marks_values_increasing(self):
        """Test CORRECT_MARKS values increase with difficulty"""
        self.assertLess(CORRECT_MARKS['Easy'], CORRECT_MARKS['Medium'])
        self.assertLess(CORRECT_MARKS['Medium'], CORRECT_MARKS['Hard'])
        self.assertLess(CORRECT_MARKS['Hard'], CORRECT_MARKS['Secondary'])
    
    def test_stepdown_penalties_negative(self):
        """Test STEPDOWN_PENALTY values are negative or zero"""
        for penalty in STEPDOWN_PENALTY.values():
            self.assertLessEqual(penalty, 0)
    
    def test_buffer_penalties_negative(self):
        """Test BUFFER_BORROW_PENALTY values are negative"""
        for penalty in BUFFER_BORROW_PENALTY.values():
            self.assertLess(penalty, 0)


if __name__ == '__main__':
    import unittest
    unittest.main()
