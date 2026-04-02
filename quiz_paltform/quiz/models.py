import uuid
from django.db import models


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class JobLevel(models.Model):

    class GenerationStatus(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        PROCESSING = 'Processing', 'Processing'
        COMPLETED = 'Completed', 'Completed'
        FAILED = 'Failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='levels')
    level_name = models.CharField(max_length=100)  # e.g., "Junior"
    jd_text = models.TextField()

    generation_status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # This ensures the JD and Level show up as a single string
        return f"{self.job.name} - {self.level_name}"


class Question(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_level = models.ForeignKey(JobLevel, on_delete=models.CASCADE, related_name='questions')
    question_prompt = models.TextField()
    difficulty = models.CharField(max_length=20)  # Easy, Medium, Hard
    type = models.CharField(max_length=20)  # MCQ, MSQ, One-Word
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.job_level} | {self.type} | {self.difficulty}"


class QuestionOption(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    option_text = models.TextField()
    is_correct = models.BooleanField(default=False)


class Quiz(models.Model):
    """A reusable template with Primary/Secondary Job Levels and Adaptive Quotas"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)

    # --- JOB LEVEL HIERARCHY ---
    # primary_job_level = models.ForeignKey(
    #     'JobLevel',
    #     on_delete=models.CASCADE,
    #     related_name='primary_quizzes'
    # )
    # secondary_job_level = models.ForeignKey(
    #     'JobLevel',
    #     on_delete=models.CASCADE,
    #     related_name='secondary_quizzes',
    #     null=True,
    #     blank=True
    # )
    primary_job_levels = models.ManyToManyField(
        'JobLevel',
        related_name='primary_quizzes'
    )
    secondary_job_levels = models.ManyToManyField(
        'JobLevel',
        related_name='secondary_quizzes',
        blank=True
    )
    easy_count = models.IntegerField(default=5)
    medium_count = models.IntegerField(default=10)
    hard_count = models.IntegerField(default=5)
    sec_easy_count = models.PositiveIntegerField(default=0)
    sec_medium_count = models.PositiveIntegerField(default=0)
    sec_hard_count = models.PositiveIntegerField(default=5)


    is_finalized = models.BooleanField(default=False)
    total_questions_limit = models.IntegerField(default=25)
    is_adaptive = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)  # Set on creation
    updated_at = models.DateTimeField(auto_now=True)  # Updates every save

    def __str__(self):
        return f"{self.title} (Created: {self.created_at.strftime('%Y-%m-%d')})"

    class Meta:
        verbose_name_plural = "Quizzes"
        ordering = ['-created_at']


class QuizQuestion(models.Model):
    class Role(models.TextChoices):
        PRIMARY = 'primary', 'Primary'
        BUFFER = 'buffer', 'Buffer'

    class Pool(models.TextChoices):
        PRIMARY_POOL = 'primary', 'Primary Pool'  # Easy/Medium/Hard from primary_job_level
        SECONDARY_POOL = 'secondary', 'Secondary Pool'  # Boss phase from secondary_job_level

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='quiz_questions')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='quiz_entries')
    difficulty = models.CharField(max_length=20)  # Easy / Medium / Hard
    role = models.CharField(max_length=10, choices=Role.choices)  # primary / buffer
    pool = models.CharField(max_length=10, choices=Pool.choices)  # primary / secondary
    order = models.PositiveIntegerField(default=0)  # for display order in admin/preview

    class Meta:
        unique_together = ('quiz', 'question')  # a question can only appear once per quiz
        ordering = ['pool', 'difficulty', 'role', 'order']
        verbose_name = "Quiz Question"
        verbose_name_plural = "Quiz Questions"

    def __str__(self):
        return f"{self.quiz.title} | {self.difficulty} | {self.role} | {self.question}"


# --- GROUP 3: THE TESTING ENGINE (Candidates & Live Tests) ---

class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=False)

    def __str__(self):
        return self.name


class Assessment(models.Model):
    """The specific 'Magic Link' instance sent to a candidate"""

    class Status(models.TextChoices):
        NOT_STARTED = 'Not_Started', 'Not Started'
        IN_PROGRESS = 'In_Progress', 'In Progress'
        COMPLETED = 'Completed', 'Completed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='assessments')
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='assessments')
    magic_link_token = models.CharField(max_length=255, unique=True)
    test_duration_mins = models.IntegerField(default=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    current_question_index = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    final_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    current_phase = models.CharField(
        max_length=20,
        choices=[('MAIN', 'Main Exam'), ('SECONDARY', 'Secondary Exam')],
        default='MAIN'
    )

    # Separate scores
    main_exam_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    secondary_exam_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Phase completion tracking
    main_exam_completed_at = models.DateTimeField(null=True, blank=True)
    secondary_exam_unlocked = models.BooleanField(default=False)

    @property
    def is_time_up(self):
        if not self.started_at:
            return False
        from django.utils import timezone
        elapsed = timezone.now() - self.started_at
        return elapsed.total_seconds() > (self.test_duration_mins * 60)
    def __str__(self):
        return f"{self.candidate.name} - {self.quiz.title}"

class TestSession(models.Model):
        id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
        assessment = models.OneToOneField(Assessment, on_delete=models.CASCADE, related_name='session')
        current_difficulty = models.CharField(max_length=10, default='Easy')
        consecutive_correct = models.IntegerField(default=0)
        consecutive_wrong = models.IntegerField(default=0)
        total_q_answered = models.IntegerField(default=0)  # Max 25
        running_score = models.IntegerField(default=0)  # Total points - penalties
        easy_pool = models.IntegerField(default=5)
        medium_pool = models.IntegerField(default=10)
        hard_pool = models.IntegerField(default=7)
        total_easy_served = models.IntegerField(default=0)
        is_gate_passed = models.BooleanField(default=False)  # True if they hit Medium level once
        current_question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True)
        is_active = models.BooleanField(default=True)  # Set to False if they fail the Easy Gate
        start_time = models.DateTimeField(auto_now_add=True)
        last_activity = models.DateTimeField(auto_now=True)

        main_q_answered = models.IntegerField(default=0)
        secondary_q_answered = models.IntegerField(default=0)

        # Separate scores for each phase
        main_running_score = models.IntegerField(default=0)
        secondary_running_score = models.IntegerField(default=0)

        # Phase 2 pool tracking (similar to Phase 1)
        sec_easy_pool = models.IntegerField(default=0)
        sec_medium_pool = models.IntegerField(default=0)
        sec_hard_pool = models.IntegerField(default=0)

        def __str__(self):
            return f"Session: {self.assessment.candidate.name} | Level: {self.current_difficulty} | Score: {self.running_score}"

        class Meta:
            verbose_name = "Test Session"
            verbose_name_plural = "Test Sessions"



class Response(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_session = models.ForeignKey(TestSession, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey('Question', on_delete=models.CASCADE)
    selected_options = models.ManyToManyField('QuestionOption', blank=True)
    typed_answer = models.CharField(max_length=255, null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    is_skipped = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)