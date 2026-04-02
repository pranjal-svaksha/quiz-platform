from django.urls import path
from . import views

urlpatterns = [
    path('', views.job_dashboard, name='job_dashboard'),
    path('jobs/', views.job_dashboard, name='job_dashboard'),
    path('jobs/delete/<uuid:job_id>/', views.delete_job, name='delete_job'),
    path('jobs/<uuid:job_id>/', views.job_detail, name='job_detail'),
    path('generate-ai/<uuid:level_id>/', views.generate_ai_questions, name='generate_ai_questions'),
    path('jobs/level/<uuid:level_id>/questions/', views.view_question_bank, name='view_question_bank'),
    path('question/<uuid:pk>/delete/', views.delete_question, name='delete_question'),
    path('level/<uuid:level_id>/delete-duplicates/', views.delete_duplicate_questions, name='delete_duplicates'),
    path('levels/edit/<uuid:level_id>/', views.edit_level, name='edit_level'),
    path('levels/delete/<uuid:level_id>/', views.delete_level, name='delete_level'),
    path('quizzes/', views.quiz_list, name='quiz_list'),
    path('quizzes/delete/<uuid:quiz_id>/', views.delete_quiz, name='delete_quiz'),
    path('quizzes/create/', views.create_quiz, name='create_quiz'),
    path('quiz/<uuid:quiz_id>/assign/', views.create_assignment, name='create_assignment'),
    # path('quizzes/<uuid:quiz_id>/questions/', views.view_quiz_questions, name='view_quiz_questions'),
    path('quizzes/<uuid:quiz_id>/questions/', views.view_finalized_quiz_questions, name='view_quiz_questions'),
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assessments/<uuid:assessment_id>/report/', views.assessment_result_detail, name='assessment_result_detail'),
    path('assessment/start/<uuid:token>/', views.start_assessment, name='start_assessment'),
    # Use 'uuid' instead of 'int'
    path('assessments/delete/<uuid:assessment_id>/', views.delete_assessment, name='delete_assessment'),
    path('take/<str:token>/', views.take_assessment, name='take_assessment'),
    path('submit/<str:token>/', views.submit_answer, name='submit_answer'),
    path('finalize_quiz_questions/<uuid:quiz_id>/', views.finalize_quiz_questions, name='finalize_quiz_questions'),
]