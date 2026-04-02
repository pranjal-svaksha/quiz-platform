from django.shortcuts import render, redirect, get_object_or_404
from .models import JobLevel, Job ,Question ,Quiz,Assessment, Candidate,Response, QuestionOption,TestSession,QuizQuestion
from .ai_services import generate_quiz_for_level
from django.core.paginator import Paginator
import uuid
import random
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
import logging
from django.db.models import Count, Min, Max



# --- 1. THE MAIN DASHBOARD (Manage Technologies) ---
def job_dashboard(request):
    """List all Jobs (Technologies) and create new ones"""
    jobs = Job.objects.all().order_by('-created_at')

    if request.method == "POST":
        name = request.POST.get('name')
        if name:
            Job.objects.get_or_create(name=name)
        return redirect('job_dashboard')

    return render(request, 'job_dashboard.html', {'jobs': jobs})


# --- 2. THE JOB DETAIL (Manage Levels/JDs) ---
def job_detail(request, job_id):
    """See all Levels (Junior, Senior) under a specific Job"""
    job = get_object_or_404(Job, id=job_id)
    levels = job.levels.all().order_by('created_at')

    if request.method == "POST":
        level_name = request.POST.get('level_name')
        jd_text = request.POST.get('jd_text')
        if level_name and jd_text:
            JobLevel.objects.create(
                job=job,
                level_name=level_name,
                jd_text=jd_text
            )
        return redirect('job_detail', job_id=job.id)

    return render(request, 'job_detail.html', {'job': job, 'levels': levels})




def delete_job(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    job.delete()
    return redirect('job_dashboard')
def edit_level(request, level_id):
    level = get_object_or_404(JobLevel, id=level_id)
    if request.method == "POST":
        level.level_name = request.POST.get('level_name')
        level.jd_text = request.POST.get('jd_text')
        level.save()
        return redirect('job_detail', job_id=level.job.id)
    return render(request, 'edit_level.html', {'level': level})

def delete_level(request, level_id):
    level = get_object_or_404(JobLevel, id=level_id)
    job_id = level.job.id
    level.delete()
    return redirect('job_detail', job_id=job_id)


# Set up logging to catch errors in your console/logs
logger = logging.getLogger(__name__)

def generate_ai_questions(request, level_id):
    level = get_object_or_404(JobLevel, id=level_id)

    # 1. Prevent overlapping requests (Race Condition Check)
    if level.generation_status == JobLevel.GenerationStatus.PROCESSING:
        messages.warning(request, f"AI is already generating questions for {level.level_name}. Please wait.")
        return redirect('job_detail', job_id=level.job.id)

    # 2. Set status to Processing immediately
    level.generation_status = JobLevel.GenerationStatus.PROCESSING
    level.save()

    try:
        # 3. Trigger the generation logic
        # Wrap in a transaction if your function doesn't handle its own saves
        success = generate_quiz_for_level(level.id)

        if success:
            level.generation_status = JobLevel.GenerationStatus.COMPLETED
            messages.success(request, f"Successfully added 75 new unique questions to {level.level_name}!")
        else:
            level.generation_status = JobLevel.GenerationStatus.FAILED
            messages.error(request, "AI generation completed but some batches failed. Please check the logs.")

    except Exception as e:
        # 4. Catch-all for API timeouts, Database locks, or AI model errors
        logger.error(f"Critical error generating questions for Level {level_id}: {str(e)}")
        level.generation_status = JobLevel.GenerationStatus.FAILED
        messages.error(request, f"A technical error occurred: {str(e)}")

    finally:
        # 5. Always save the level status, no matter what happens in the 'try' block
        level.save()

    # 6. Return to the detail page
    return redirect('job_detail', job_id=level.job.id)




def view_question_bank(request, level_id):
    level = get_object_or_404(JobLevel, id=level_id)

    # 1. Find prompts that appear more than once for this specific level
    duplicate_prompts = level.questions.values('question_prompt').annotate(
        prompt_count=Count('question_prompt')
    ).filter(prompt_count__gt=1).values_list('question_prompt', flat=True)

    # 2. Get the actual question objects that have those duplicate prompts
    # We use question_prompt instead of text_hash here
    duplicate_questions = level.questions.filter(
        question_prompt__in=duplicate_prompts
    ).prefetch_related('options').order_by('question_prompt')

    # 3. Regular pagination logic
    all_questions = level.questions.prefetch_related('options').all().order_by('difficulty', 'id')
    paginator = Paginator(all_questions, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'level': level,
        'page_obj': page_obj,
        'duplicate_questions': duplicate_questions,
        'duplicate_count': duplicate_questions.count(),
        'total_count': all_questions.count(),
    }
    return render(request, 'question_bank.html', context)


def delete_duplicate_questions(request, level_id):
    level = get_object_or_404(JobLevel, id=level_id)

    # 1. Find all prompts that appear more than once
    duplicates = level.questions.values('question_prompt').annotate(
        min_id=Min('id'),
        count=Count('id')
    ).filter(count__gt=1)

    if not duplicates.exists():
        messages.info(request, "No duplicate questions found.")
        return redirect('view_question_bank', level_id=level.id)

    total_deleted = 0

    # 2. For each set of duplicates, delete everything EXCEPT the min_id
    for item in duplicates:
        prompt = item['question_prompt']
        keep_id = item['min_id']

        # Filter all questions with this prompt but NOT the one we want to keep
        deleted_count, _ = level.questions.filter(
            question_prompt=prompt
        ).exclude(id=keep_id).delete()

        total_deleted += deleted_count

    messages.success(request, f"Cleaned up! Removed {total_deleted} duplicate questions.")
    return redirect('view_question_bank', level_id=level.id)

def delete_question(request, pk):
    question = get_object_or_404(Question, pk=pk)

    # Use 'job_level' because that is the name of your ForeignKey
    # Pro-tip: use .job_level_id to get the ID without an extra DB query
    level_id = question.job_level_id

    question.delete()

    messages.success(request, "Question deleted successfully.")

    # Redirect back to the question bank for that specific level
    return redirect('view_question_bank', level_id=level_id)



def quiz_list(request):
    """View all created Quiz Templates with optimized database fetching"""
    # select_related joins the Job and JobLevel tables so the page loads instantly
    # Use prefetch_related and make sure the names match your new ManyToMany fields
    quizzes = Quiz.objects.prefetch_related('primary_job_levels', 'secondary_job_levels').all().order_by('-created_at')

    return render(request, 'quiz_list.html', {'quizzes': quizzes})
def delete_quiz(request, quiz_id):
    if request.method == "POST":
        quiz = get_object_or_404(Quiz, id=quiz_id)
        quiz.delete()
    return redirect('quiz_list')

# def create_quiz(request):
#     """Form to create a new Adaptive Quiz with strict 1:1 Mirror Validation"""
#     levels = JobLevel.objects.all().select_related('job')
#
#     if request.method == "POST":
#         title = request.POST.get('title')
#         p_level_id = request.POST.get('primary_level')
#         s_level_id = request.POST.get('secondary_level')
#
#         # 1. Parse Quotas
#         try:
#             e_q = int(request.POST.get('easy_count', 5))
#             m_q = int(request.POST.get('medium_count', 10))
#             h_q = int(request.POST.get('hard_count', 5))
#             sec_q = int(request.POST.get('sec_count', 5))
#         except ValueError:
#             messages.error(request, "Quotas must be valid numbers.")
#             return render(request, 'create_quiz.html', {'levels': levels})
#
#         # 2. Define Pools
#         p_pool = Question.objects.filter(job_level_id=p_level_id)
#         # If no secondary level is picked, the "Boss Phase" pulls from the Primary Level pool
#         s_pool = Question.objects.filter(job_level_id=s_level_id) if s_level_id else p_pool
#
#         error_found = False
#
#         # 3. Validation Logic: Primary Pool (Easy, Medium, Hard)
#         primary_validation = [
#             ('Easy', e_q * 2),
#             ('Medium', m_q * 2),
#             ('Hard', h_q * 2),
#         ]
#
#         for diff, required in primary_validation:
#             actual = p_pool.filter(difficulty=diff).count()
#             if actual < required:
#                 messages.error(request,
#                                f"Not enough {diff} questions in Primary Pool. Need {required} unique Qs (1:1 Mirror), but only {actual} exist.")
#                 error_found = True
#
#         # 4. Validation Logic: Secondary JOB LEVEL (The Boss Phase)
#         # We look for 'Hard' difficulty questions in the Secondary Job Level
#         sec_required = sec_q * 2
#
#         # If Secondary Job Level is the SAME as Primary, we must subtract the Hard Qs already used
#         if s_level_id == p_level_id or not s_level_id:
#             sec_actual = s_pool.filter(difficulty='Hard').count() - (h_q * 2)
#         else:
#             # If it's a different Job Level, we have the whole Hard pool available
#             sec_actual = s_pool.filter(difficulty='Hard').count()
#
#         if sec_actual < sec_required:
#             messages.error(request,
#                            f"Not enough high-level questions in Secondary Job Level. Need {sec_required} unique Qs, but only {max(0, sec_actual)} are available.")
#             error_found = True
#
#         if error_found:
#             return render(request, 'create_quiz.html', {'levels': levels})
#
#         calculated_total = e_q + m_q + h_q + sec_q
#
#         # 2. Update the Create call
#         new_quiz = Quiz.objects.create(
#             title=title,
#             primary_job_level_id=p_level_id,
#             secondary_job_level_id=s_level_id if s_level_id else None,
#             easy_count=e_q,
#             medium_count=m_q,
#             hard_count=h_q,
#             secondary_exam_count=sec_q,
#             # Use the variable instead of the hardcoded 25
#             total_questions_limit=calculated_total
#         )
#
#         messages.success(request, f"Quiz '{title}' created successfully with 1:1 Mirrors!")
#         return redirect('quiz_list')
#
#     return render(request, 'create_quiz.html', {'levels': levels})
def create_quiz(request):
    levels = JobLevel.objects.all().select_related('job')

    if request.method == "POST":
        title = request.POST.get('title')
        # Capture multiple IDs from the form
        p_level_ids = request.POST.getlist('primary_levels')
        s_level_ids = request.POST.getlist('secondary_levels')

        try:
            # Phase 1 Counts
            e_q = int(request.POST.get('easy_count', 0))
            m_q = int(request.POST.get('medium_count', 0))
            h_q = int(request.POST.get('hard_count', 0))
            # Phase 2 Counts
            se_e = int(request.POST.get('sec_easy_count', 0))
            se_m = int(request.POST.get('sec_medium_count', 0))
            se_h = int(request.POST.get('sec_hard_count', 0))
        except ValueError:
            messages.error(request, "Counts must be valid numbers.")
            return render(request, 'create_quiz.html', {'levels': levels})

        # Define Pools across ALL selected levels
        p_pool = Question.objects.filter(job_level_id__in=p_level_ids)
        s_pool = Question.objects.filter(job_level_id__in=s_level_ids) if s_level_ids else p_pool

        error_found = False

        # Validation Logic: Primary
        for diff, req in [('Easy', e_q), ('Medium', m_q), ('Hard', h_q)]:
            actual = p_pool.filter(difficulty=diff).count()
            if actual < (req * 2):
                messages.error(request,
                               f"Not enough {diff} questions in Primary Levels. Need {req * 2}, found {actual}.")
                error_found = True

        # Validation Logic: Secondary (Accounting for overlap)
        is_same_pool = not s_level_ids or set(p_level_ids) == set(s_level_ids)

        for diff, req, p_req in [('Easy', se_e, e_q), ('Medium', se_m, m_q), ('Hard', se_h, h_q)]:
            # If pools are identical, subtract the unique ones already "reserved" for Phase 1
            reserved = (p_req * 2) if is_same_pool else 0
            actual = s_pool.filter(difficulty=diff).count() - reserved
            if actual < (req * 2):
                messages.error(request,
                               f"Not enough {diff} questions in Secondary Levels. Need {req * 2}, found {max(0, actual)} available.")
                error_found = True

        if error_found:
            return render(request, 'create_quiz.html', {'levels': levels})

        # Create the Quiz object
        total_limit = e_q + m_q + h_q + se_e + se_m + se_h
        new_quiz = Quiz.objects.create(
            title=title,
            easy_count=e_q,
            medium_count=m_q,
            hard_count=h_q,
            sec_easy_count=se_e,
            sec_medium_count=se_m,
            sec_hard_count=se_h,
            total_questions_limit=total_limit
        )

        # Set ManyToMany relationships (must happen AFTER .create())
        new_quiz.primary_job_levels.set(p_level_ids)
        if s_level_ids:
            new_quiz.secondary_job_levels.set(s_level_ids)

        messages.success(request, f"Quiz '{title}' created successfully!")
        return redirect('quiz_list')

    return render(request, 'create_quiz.html', {'levels': levels})



def view_quiz_questions(request, quiz_id):
    # Use prefetch_related for ManyToMany fields
    quiz = get_object_or_404(
        Quiz.objects.prefetch_related('primary_job_levels', 'secondary_job_levels'),
        id=quiz_id
    )

    # --- 1. If finalized: show the SAVED fixed question set ---
    if quiz.is_finalized:
        saved_qs = QuizQuestion.objects.filter(quiz=quiz).select_related(
            'question'
        ).prefetch_related('question__options')

        # Updated structure to support granular Boss Phase difficulties
        finalized_data = {
            'Primary': {'Easy': [], 'Medium': [], 'Hard': []},
            'Secondary': {'Easy': [], 'Medium': [], 'Hard': []}
        }

        for qq in saved_qs:
            pool_key = 'Secondary' if qq.pool == 'SECONDARY' else 'Primary'
            finalized_data[pool_key][qq.difficulty].append(qq.question)

        return render(request, 'view_quiz_questions.html', {
            'quiz': quiz,
            'is_finalized': True,
            'finalized_data': finalized_data,
        })

    # --- 2. Not finalized: show PREVIEW (Random Sample) ---

    # Define Primary Pool from ALL selected primary levels
    p_level_ids = quiz.primary_job_levels.values_list('id', flat=True)
    p_pool = list(Question.objects.filter(job_level_id__in=p_level_ids).prefetch_related('options'))

    # Define Secondary Pool (Boss Phase)
    s_level_ids = quiz.secondary_job_levels.values_list('id', flat=True)
    if not s_level_ids:
        s_level_ids = p_level_ids  # Fallback to primary if none selected
    s_pool = list(Question.objects.filter(job_level_id__in=s_level_ids).prefetch_related('options'))

    def get_preview_data(pool, counts_dict):
        """Helper to sample primary and buffer questions"""
        results = {}
        # We use a set to track used IDs to ensure no duplicates if pools overlap
        used_ids = set()

        for diff, count in counts_dict.items():
            # Filter pool by difficulty and exclude already picked questions
            available = [q for q in pool if q.difficulty == diff and q.id not in used_ids]
            needed = count * 2  # 1 Primary + 1 Mirror Buffer

            if len(available) >= needed:
                selected = random.sample(available, needed)
                primary_qs = selected[:count]
                buffer_qs = selected[count:]
                # Mark as used so they aren't picked again in later difficulties or phases
                for q in selected: used_ids.add(q.id)
            else:
                primary_qs = available
                buffer_qs = []

            results[diff] = {
                'primary': primary_qs,
                'buffer': buffer_qs,
                'req': count
            }
        return results

    # Generate Primary Preview
    primary_counts = {
        'Easy': quiz.easy_count,
        'Medium': quiz.medium_count,
        'Hard': quiz.hard_count
    }
    simulated_primary = get_preview_data(p_pool, primary_counts)

    # Generate Secondary Preview (Boss Phase)
    secondary_counts = {
        'Easy': quiz.sec_easy_count,
        'Medium': quiz.sec_medium_count,
        'Hard': quiz.sec_hard_count
    }
    simulated_secondary = get_preview_data(s_pool, secondary_counts)

    context = {
        'quiz': quiz,
        'is_finalized': False,
        'simulated_primary': simulated_primary,
        'simulated_secondary': simulated_secondary,
    }
    return render(request, 'view_quiz_questions.html', context)


def assignment_list(request):
    """View all sent assessments and their status"""
    assessments = Assessment.objects.all().order_by('-id')
    return render(request, 'assignment_list.html', {'assessments': assessments})
def delete_assessment(request, assessment_id):
    if request.method == "POST":
        # assessment_id will now correctly be a UUID object
        assessment = get_object_or_404(Assessment, id=assessment_id)
        assessment.delete()
    return redirect('assignment_list')


# def assessment_result_detail(request, assessment_id):
#     # Fetch assessment with related candidate and quiz data
#     assessment = get_object_or_404(
#         Assessment.objects.select_related('candidate', 'quiz', 'session'),
#         id=assessment_id
#     )
#
#     session = assessment.session
#     # Fetch all responses with questions and options to avoid N+1 queries
#     # Change .order_id to .order_by
#     responses = Response.objects.filter(test_session=session).select_related('question').prefetch_related(
#         'selected_options', 'question__options').order_by('timestamp')
#
#     # Breakdown by Difficulty
#     stats = {
#         'easy': responses.filter(question__difficulty='Easy').count(),
#         'medium': responses.filter(question__difficulty='Medium').count(),
#         'hard': responses.filter(question__difficulty='Hard').count(),
#         'correct': responses.filter(is_correct=True).count(),
#         'wrong': responses.filter(is_correct=False, is_skipped=False).count(),
#         'skipped': responses.filter(is_skipped=True).count(),
#     }
#
#     # Identify if Buffer questions were used
#     # A question is a 'Buffer' if it was part of the QuizQuestion pool as a Role.BUFFER
#     # We'll tag the response list for the template
#     detailed_responses = []
#     for resp in responses:
#         # Check the role in the QuizQuestion join table
#         from .models import QuizQuestion
#         quiz_rel = QuizQuestion.objects.filter(quiz=assessment.quiz, question=resp.question).first()
#
#         detailed_responses.append({
#             'obj': resp,
#             'is_buffer': quiz_rel.role == 'buffer' if quiz_rel else False,
#             'difficulty': resp.question.difficulty,
#         })
#
#     return render(request, 'assessment_report.html', {
#         'assessment': assessment,
#         'session': session,
#         'stats': stats,
#         'responses': detailed_responses
#     })

def assessment_result_detail(request, assessment_id):
    # Fetch assessment with related candidate and quiz data
    assessment = get_object_or_404(
        Assessment.objects.select_related('candidate', 'quiz', 'session'),
        id=assessment_id
    )

    session = assessment.session
    quiz = assessment.quiz

    # Fetch all responses in chronological order
    responses = Response.objects.filter(test_session=session).select_related(
        'question'
    ).prefetch_related(
        'selected_options',
        'question__options'
    ).order_by('timestamp')

    # Get QuizQuestion relationships to determine buffer, pool, and difficulty
    from .models import QuizQuestion
    quiz_questions = QuizQuestion.objects.filter(quiz=quiz).select_related('question')

    # Build lookup maps
    question_metadata = {}
    for qq in quiz_questions:
        question_metadata[qq.question_id] = {
            'is_buffer': qq.role == QuizQuestion.Role.BUFFER,
            'pool': qq.pool,
            'difficulty': qq.difficulty,
        }

    # Calculate max possible scores for both phases
    max_main = (
            quiz.easy_count * MAIN_MARKS['Easy'] +
            quiz.medium_count * MAIN_MARKS['Medium'] +
            quiz.hard_count * MAIN_MARKS['Hard']
    )

    max_secondary = (
            quiz.sec_easy_count * SECONDARY_MARKS['Easy'] +
            quiz.sec_medium_count * SECONDARY_MARKS['Medium'] +
            quiz.sec_hard_count * SECONDARY_MARKS['Hard']
    )

    main_threshold = max_main * 0.65
    secondary_threshold = max_secondary * 0.65

    # Simulate the entire test to track score changes
    detailed_responses = []

    # Phase tracking
    current_phase = 'MAIN'
    main_q_count = 0
    secondary_q_count = 0

    # Scoring
    main_running_score = 0
    secondary_running_score = 0

    # Adaptive tracking
    current_difficulty = 'Easy'
    consecutive_correct = 0
    consecutive_wrong = 0

    # Statistics
    main_difficulty_count = {'Easy': 0, 'Medium': 0, 'Hard': 0}
    secondary_difficulty_count = {'Easy': 0, 'Medium': 0, 'Hard': 0}
    main_skipped = 0
    secondary_skipped = 0

    # Phase transition tracking
    main_exam_ended_at_index = None
    secondary_exam_started_at_index = None

    for idx, resp in enumerate(responses, 1):
        # Get metadata for this question
        metadata = question_metadata.get(resp.question_id, {
            'is_buffer': False,
            'pool': QuizQuestion.Pool.PRIMARY_POOL,
            'difficulty': resp.question.difficulty,
        })

        is_buffer = metadata['is_buffer']
        pool = metadata['pool']
        question_difficulty = metadata['difficulty']

        # Determine which phase this question belongs to
        is_secondary_pool = pool == QuizQuestion.Pool.SECONDARY_POOL

        # Phase transition detection
        if current_phase == 'MAIN' and is_secondary_pool:
            # Transition to secondary exam
            current_phase = 'SECONDARY'
            main_exam_ended_at_index = idx - 1
            secondary_exam_started_at_index = idx

            # Reset adaptive parameters for secondary phase
            current_difficulty = 'Easy'
            consecutive_correct = 0
            consecutive_wrong = 0

        # Count questions by phase
        if current_phase == 'MAIN':
            main_q_count += 1
            main_difficulty_count[question_difficulty] += 1
            if resp.is_skipped:
                main_skipped += 1
        else:
            secondary_q_count += 1
            secondary_difficulty_count[question_difficulty] += 1
            if resp.is_skipped:
                secondary_skipped += 1

        # Select appropriate marks and threshold based on phase
        if current_phase == 'MAIN':
            marks_dict = MAIN_MARKS
            current_score = main_running_score
            threshold = main_threshold
            difficulty_order = MAIN_DIFFICULTY_ORDER
        else:
            marks_dict = SECONDARY_MARKS
            current_score = secondary_running_score
            threshold = secondary_threshold
            difficulty_order = SECONDARY_DIFFICULTY_ORDER

        # FIRST: Apply buffer penalty (happens BEFORE answering, when question is served)
        buffer_penalty = 0
        if is_buffer and current_score < threshold:
            buffer_penalty = BUFFER_BORROW_PENALTY.get(question_difficulty, -1)
            if current_phase == 'MAIN':
                main_running_score += buffer_penalty
            else:
                secondary_running_score += buffer_penalty

        # SECOND: Calculate marks awarded for answering this question
        marks_awarded = 0
        if resp.is_correct and not resp.is_skipped:
            marks_awarded = marks_dict.get(question_difficulty, 0)
            if current_phase == 'MAIN':
                main_running_score += marks_awarded
            else:
                secondary_running_score += marks_awarded

        # THIRD: Simulate process_answer logic for promotions/demotions
        demotion_penalty = 0
        promotion_demotion = ''

        if resp.is_correct and not resp.is_skipped:
            # CORRECT answer
            consecutive_correct += 1
            consecutive_wrong = 0

            if consecutive_correct >= 2:
                idx_diff = difficulty_order.index(current_difficulty)
                if idx_diff < len(difficulty_order) - 1:
                    new_diff = difficulty_order[idx_diff + 1]
                    promotion_demotion = f'Promoted: {current_difficulty} → {new_diff}'
                    current_difficulty = new_diff
                    consecutive_correct = 0
                    consecutive_wrong = 0
        else:
            # WRONG or SKIPPED answer
            consecutive_wrong += 1
            consecutive_correct = 0

            if consecutive_wrong >= 2:
                idx_diff = difficulty_order.index(current_difficulty)
                if idx_diff > 0:
                    prev_diff = difficulty_order[idx_diff - 1]
                    demotion_penalty = STEPDOWN_PENALTY.get((current_difficulty, prev_diff), 0)

                    if current_phase == 'MAIN':
                        main_running_score += demotion_penalty
                    else:
                        secondary_running_score += demotion_penalty

                    promotion_demotion = f'Demoted: {current_difficulty} → {prev_diff} ({demotion_penalty} marks)'
                    current_difficulty = prev_diff
                    consecutive_correct = 0
                    consecutive_wrong = 0

        # Get correct answer(s)
        correct_options = list(resp.question.options.filter(is_correct=True))
        correct_answer = ', '.join([opt.option_text for opt in correct_options])

        # Get candidate's answer
        if resp.is_skipped:
            candidate_answer = "Skipped"
        elif resp.question.type == 'One-Word':
            candidate_answer = resp.typed_answer or "No answer"
        else:
            selected = list(resp.selected_options.all())
            candidate_answer = ', '.join([opt.option_text for opt in selected]) if selected else "No selection"

        # Update running score for display
        if current_phase == 'MAIN':
            running_score = main_running_score
        else:
            running_score = secondary_running_score

        detailed_responses.append({
            'serial': idx,
            'phase': current_phase,
            'phase_question_number': main_q_count if current_phase == 'MAIN' else secondary_q_count,
            'question': resp.question,
            'question_type': resp.question.type,
            'is_buffer': is_buffer,
            'is_secondary_pool': is_secondary_pool,
            'difficulty': question_difficulty,
            'candidate_answer': candidate_answer,
            'correct_answer': correct_answer,
            'is_correct': resp.is_correct,
            'is_skipped': resp.is_skipped,
            'marks_awarded': marks_awarded,
            'buffer_penalty': buffer_penalty,
            'demotion_penalty': demotion_penalty,
            'promotion_demotion': promotion_demotion,
            'running_score': running_score,
            'timestamp': resp.timestamp,
        })

    # Calculate final percentages
    main_percentage = round((main_running_score / max_main) * 100, 2) if max_main > 0 else 0
    secondary_percentage = round((secondary_running_score / max_secondary) * 100, 2) if max_secondary > 0 else 0

    # Determine if candidate qualified for secondary
    qualified_for_secondary = main_percentage >= (SECONDARY_UNLOCK_THRESHOLD * 100)
    actually_attempted_secondary = secondary_q_count > 0

    # Overall statistics
    context = {
        'assessment': assessment,
        'responses': detailed_responses,

        # Phase information
        'main_exam_ended_at_index': main_exam_ended_at_index,
        'secondary_exam_started_at_index': secondary_exam_started_at_index,

        # Main exam stats
        'main_score': main_running_score,
        'main_max_score': max_main,
        'main_percentage': main_percentage,
        'main_difficulty_count': main_difficulty_count,
        'main_total_questions': main_q_count,
        'main_skipped': main_skipped,
        'main_correct': sum(1 for r in detailed_responses if r['phase'] == 'MAIN' and r['is_correct']),
        'main_wrong': sum(
            1 for r in detailed_responses if r['phase'] == 'MAIN' and not r['is_correct'] and not r['is_skipped']),

        # Secondary exam stats
        'secondary_score': secondary_running_score,
        'secondary_max_score': max_secondary,
        'secondary_percentage': secondary_percentage,
        'secondary_difficulty_count': secondary_difficulty_count,
        'secondary_total_questions': secondary_q_count,
        'secondary_skipped': secondary_skipped,
        'secondary_correct': sum(1 for r in detailed_responses if r['phase'] == 'SECONDARY' and r['is_correct']),
        'secondary_wrong': sum(
            1 for r in detailed_responses if r['phase'] == 'SECONDARY' and not r['is_correct'] and not r['is_skipped']),

        # Qualification status
        'qualified_for_secondary': qualified_for_secondary,
        'attempted_secondary': actually_attempted_secondary,
        'secondary_unlock_threshold': SECONDARY_UNLOCK_THRESHOLD * 100,

        # Session data for comparison
        'session_main_score': session.main_running_score,
        'session_secondary_score': session.secondary_running_score,
        'session_total_answered': session.total_q_answered,

        # Overall
        'total_questions': len(detailed_responses),
    }

    return render(request, 'assessment_report.html', context)
# def create_assignment(request, quiz_id):
#     quiz = get_object_or_404(Quiz, id=quiz_id)
#
#     if request.method == "POST":
#         # --- NEW GUARD: Check if finalized ---
#         if not quiz.is_finalized:
#             messages.error(
#                 request,
#                 f"Cannot assign '{quiz.title}' because the questions are not finalized yet. "
#                 f"Please finalize the questions first."
#             )
#             return render(request, 'create_assignment.html', {'quiz': quiz})
#
#         # --- EXISTING LOGIC ---
#         c_name = request.POST.get('candidate_name')
#         c_email = request.POST.get('candidate_email')
#         time_limit = int(request.POST.get('time_limit', 30))
#
#         candidate, _ = Candidate.objects.get_or_create(
#             email=c_email, defaults={'name': c_name}
#         )
#
#         # Generate assessment and token
#         assessment = Assessment.objects.create(
#             quiz=quiz,
#             candidate=candidate,
#             magic_link_token=str(uuid.uuid4()),
#             test_duration_mins=time_limit
#         )
#
#         # Initialize Session
#         TestSession.objects.create(
#             assessment=assessment,
#             easy_pool=quiz.easy_count,
#             medium_pool=quiz.medium_count,
#             hard_pool=quiz.hard_count,
#             current_difficulty='Easy'
#         )
#
#         # Build the URL
#         full_link = f"{request.scheme}://{request.get_host()}/take/{assessment.magic_link_token}/"
#
#         messages.success(request, full_link, extra_tags='magic_link')
#         return redirect('quiz_list')
#
#     return render(request, 'create_assignment.html', {'quiz': quiz})
def create_assignment(request, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id)
    all_candidates = Candidate.objects.all().order_by('name')

    if request.method == "POST":
        if not quiz.is_finalized:
            messages.error(request, "Finalize the quiz first.")
            return redirect('view_quiz_questions', quiz_id=quiz.id)

        # 1. Get the choice from the dropdown
        selected_id = request.POST.get('existing_candidate_id')

        # 2. Logic to determine which candidate to use
        if selected_id and selected_id != 'new':
            # Use Existing
            candidate = get_object_or_404(Candidate, id=selected_id)
        else:
            # Create New
            c_name = request.POST.get('candidate_name')
            c_email = request.POST.get('candidate_email')

            if not c_name or not c_email:
                messages.error(request, "Please provide a name and email for the new candidate.")
                return render(request, 'create_assignment.html', {'quiz': quiz, 'candidates': all_candidates})

            # get_or_create ensures we don't duplicate emails if they already exist
            candidate, created = Candidate.objects.get_or_create(
                email=c_email,
                defaults={'name': c_name}
            )

        # 3. Create the Assessment linked to that candidate
        assessment = Assessment.objects.create(
            quiz=quiz,
            candidate=candidate,  # <-- CRITICAL: This links the name/email to the assessment
            magic_link_token=str(uuid.uuid4()),
            test_duration_mins=int(request.POST.get('time_limit', 30))
        )

        # 4. Initialize Session
        TestSession.objects.create(
            assessment=assessment,
            easy_pool=quiz.easy_count,
            medium_pool=quiz.medium_count,
            hard_pool=quiz.hard_count,
            current_difficulty='Easy'
        )

        full_link = f"{request.scheme}://{request.get_host()}/take/{assessment.magic_link_token}/"
        messages.success(request, full_link, extra_tags='magic_link')
        return redirect('quiz_list')

    return render(request, 'create_assignment.html', {
        'quiz': quiz,
        'candidates': all_candidates
    })


@transaction.atomic
def finalize_quiz_questions(request, quiz_id):
    if request.method != "POST":
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    quiz = get_object_or_404(Quiz, id=quiz_id)
    if quiz.is_finalized:
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    # 1. Get IDs for all selected levels
    p_level_ids = quiz.primary_job_levels.values_list('id', flat=True)
    s_level_ids = quiz.secondary_job_levels.values_list('id', flat=True)
    if not s_level_ids:
        s_level_ids = p_level_ids

    used_question_ids = []

    # --- Helper to Save Questions to Join Table ---
    def save_pool_to_db(level_ids, counts_dict, pool_type):
        for diff, count in counts_dict.items():
            if count <= 0: continue

            needed = count * 2
            available = list(Question.objects.filter(
                job_level_id__in=level_ids,
                difficulty=diff
            ).exclude(id__in=used_question_ids))

            if len(available) < needed:
                # Fallback if pool is too small, just take what's left
                selected = available
            else:
                selected = random.sample(available, needed)

            # Mark as used so we don't duplicate across phases
            for q in selected:
                used_question_ids.append(q.id)

            # Save Primary and Buffer roles
            for i, q in enumerate(selected):
                role = QuizQuestion.Role.PRIMARY if i < count else QuizQuestion.Role.BUFFER
                QuizQuestion.objects.create(
                    quiz=quiz,
                    question=q,
                    difficulty=diff,
                    pool=pool_type,
                    role=role
                )

    # 2. Finalize Primary Phase
    primary_counts = {'Easy': quiz.easy_count, 'Medium': quiz.medium_count, 'Hard': quiz.hard_count}
    save_pool_to_db(p_level_ids, primary_counts, QuizQuestion.Pool.PRIMARY_POOL)

    # 3. Finalize Secondary (Boss) Phase
    secondary_counts = {'Easy': quiz.sec_easy_count, 'Medium': quiz.sec_medium_count, 'Hard': quiz.sec_hard_count}
    save_pool_to_db(s_level_ids, secondary_counts, QuizQuestion.Pool.SECONDARY_POOL)

    # 4. Lock the Quiz
    quiz.is_finalized = True
    quiz.save()

    messages.success(request, f"Question pool for '{quiz.title}' has been locked successfully.")
    return redirect('view_quiz_questions', quiz_id=quiz_id)


def view_finalized_quiz_questions(request, quiz_id):
    # Use prefetch_related for the many-to-many fields
    quiz = get_object_or_404(
        Quiz.objects.prefetch_related('primary_job_levels', 'secondary_job_levels'),
        id=quiz_id
    )

    # Initialize the structures the template expects
    simulated_test = {}
    secondary_data = {'primary': [], 'buffer': []}

    # New structure for granular boss phase preview
    simulated_secondary = {}

    if quiz.is_finalized:
        # --- 1. FETCH FROM THE JOIN TABLE (LOCKED DATA) ---
        all_relations = QuizQuestion.objects.filter(quiz=quiz).select_related('question').prefetch_related(
            'question__options')

        # Primary Pool Recovery
        for diff_choice in ['Easy', 'Medium', 'Hard']:
            diff_qs = all_relations.filter(pool=QuizQuestion.Pool.PRIMARY_POOL, difficulty=diff_choice)
            if diff_qs.exists():
                simulated_test[diff_choice] = {
                    'req': diff_qs.filter(role=QuizQuestion.Role.PRIMARY).count(),
                    'primary': [rel.question for rel in diff_qs.filter(role=QuizQuestion.Role.PRIMARY)],
                    'buffer': [rel.question for rel in diff_qs.filter(role=QuizQuestion.Role.BUFFER)],
                }

        # Secondary (Boss) Pool Recovery - Updated for granular difficulties
        for diff_choice in ['Easy', 'Medium', 'Hard']:
            boss_diff_qs = all_relations.filter(pool=QuizQuestion.Pool.SECONDARY_POOL, difficulty=diff_choice)
            if boss_diff_qs.exists():
                simulated_secondary[diff_choice] = {
                    'req': boss_diff_qs.filter(role=QuizQuestion.Role.PRIMARY).count(),
                    'primary': [rel.question for rel in boss_diff_qs.filter(role=QuizQuestion.Role.PRIMARY)],
                    'buffer': [rel.question for rel in boss_diff_qs.filter(role=QuizQuestion.Role.BUFFER)],
                }

    else:
        # --- 2. LOGIC FOR PREVIEW (RANDOM SAMPLING ON THE FLY) ---
        p_level_ids = quiz.primary_job_levels.values_list('id', flat=True)
        s_level_ids = quiz.secondary_job_levels.values_list('id', flat=True)
        if not s_level_ids:
            s_level_ids = p_level_ids

        used_ids = []

        # A. Primary Pool Preview (Using __in for ManyToMany)
        primary_configs = [
            ('Easy', quiz.easy_count),
            ('Medium', quiz.medium_count),
            ('Hard', quiz.hard_count)
        ]

        for diff, count in primary_configs:
            needed = count * 2
            available = list(Question.objects.filter(
                job_level_id__in=p_level_ids,
                difficulty=diff
            ).prefetch_related('options'))

            if len(available) >= needed:
                selected = random.sample(available, needed)
                simulated_test[diff] = {
                    'req': count,
                    'primary': selected[:count],
                    'buffer': selected[count:],
                }
                used_ids.extend([q.id for q in selected])
            else:
                simulated_test[diff] = {'req': count, 'primary': available, 'buffer': []}

        # B. Secondary Pool (Boss Phase) Preview - Updated for new counts
        secondary_configs = [
            ('Easy', quiz.sec_easy_count),
            ('Medium', quiz.sec_medium_count),
            ('Hard', quiz.sec_hard_count)
        ]

        for diff, count in secondary_configs:
            if count == 0: continue

            needed = count * 2
            available = list(Question.objects.filter(
                job_level_id__in=s_level_ids,
                difficulty=diff
            ).exclude(id__in=used_ids).prefetch_related('options'))

            if len(available) >= needed:
                selected = random.sample(available, needed)
                simulated_secondary[diff] = {
                    'req': count,
                    'primary': selected[:count],
                    'buffer': selected[count:],
                }
                used_ids.extend([q.id for q in selected])
            else:
                simulated_secondary[diff] = {'req': count, 'primary': available, 'buffer': []}

    return render(request, 'view_quiz_questions.html', {
        'quiz': quiz,
        'simulated_primary': simulated_test,  # Renamed to match the template logic
        'simulated_secondary': simulated_secondary,  # New granular structure
        'is_finalized': quiz.is_finalized
    })
# ============================================================
#  CONSTANTS
# ============================================================
"""
CORRECT_MARKS = {
    'Easy':      1,
    'Medium':    2,
    'Hard':      5,
    'Secondary': 10,
}

STEPDOWN_PENALTY = {
    ('Hard',      'Medium'): -2,
    ('Medium',    'Easy'):   -1,
    ('Secondary', 'Hard'):    0,
}

BUFFER_BORROW_PENALTY = {
    'Easy':      -1,
    'Medium':    -2,
    'Hard':      -2,
    'Secondary': -2,
}

DIFFICULTY_ORDER = ['Easy', 'Medium', 'Hard', 'Secondary']

# TestSession field that tracks primary pool remaining per level
POOL_FIELD = {
    'Easy':   'easy_pool',
    'Medium': 'medium_pool',
    'Hard':   'hard_pool',
}

# (db_pool, db_difficulty) to query QuizQuestion per stage
DB_POOL = {
    'Easy':      (QuizQuestion.Pool.PRIMARY_POOL,   'Easy'),
    'Medium':    (QuizQuestion.Pool.PRIMARY_POOL,   'Medium'),
    'Hard':      (QuizQuestion.Pool.PRIMARY_POOL,   'Hard'),
    'Secondary': (QuizQuestion.Pool.SECONDARY_POOL, 'Hard'),
}

# Which level's primary pool shrinks when buffer is borrowed
NEXT_LEVEL = {
    'Easy':      'Medium',
    'Medium':    'Hard',
    'Hard':      'Secondary',
    'Secondary': None,
}
"""
# Remove 'Secondary' from main difficulty order
CORRECT_MARKS = {
    'Easy':      1,
    'Medium':    2,
    'Hard':      5,
}

# Remove the old unified marks - now we have separate ones
MAIN_MARKS = {
    'Easy': 1,
    'Medium': 2,
    'Hard': 5,
}

SECONDARY_MARKS = {
    'Easy': 1,
    'Medium': 2,
    'Hard': 5,
}

STEPDOWN_PENALTY = {
    ('Hard', 'Medium'): -2,
    ('Medium', 'Easy'): -1,
    # Remove the old ('Secondary', 'Hard'): 0,
}

BUFFER_BORROW_PENALTY = {
    'Easy':   -1,
    'Medium': -2,
    'Hard':   -2,
}

# OLD - Remove this
# DIFFICULTY_ORDER = ['Easy', 'Medium', 'Hard', 'Secondary']

# NEW - Separate orders for each phase
MAIN_DIFFICULTY_ORDER = ['Easy', 'Medium', 'Hard']
SECONDARY_DIFFICULTY_ORDER = ['Easy', 'Medium', 'Hard']

# Pool field mapping - separate for each phase
MAIN_POOL_FIELD = {
    'Easy':   'easy_pool',
    'Medium': 'medium_pool',
    'Hard':   'hard_pool',
}

SECONDARY_POOL_FIELD = {
    'Easy':   'sec_easy_pool',
    'Medium': 'sec_medium_pool',
    'Hard':   'sec_hard_pool',
}

# DB query mapping - separate for each phase
DB_POOL_MAIN = {
    'Easy':   (QuizQuestion.Pool.PRIMARY_POOL, 'Easy'),
    'Medium': (QuizQuestion.Pool.PRIMARY_POOL, 'Medium'),
    'Hard':   (QuizQuestion.Pool.PRIMARY_POOL, 'Hard'),
}

DB_POOL_SECONDARY = {
    'Easy':   (QuizQuestion.Pool.SECONDARY_POOL, 'Easy'),
    'Medium': (QuizQuestion.Pool.SECONDARY_POOL, 'Medium'),
    'Hard':   (QuizQuestion.Pool.SECONDARY_POOL, 'Hard'),
}

# FIX: NEXT_LEVEL - now only goes up to Hard (no 'Secondary' level)
NEXT_LEVEL = {
    'Easy':   'Medium',
    'Medium': 'Hard',
    'Hard':   None,  # No next level after Hard
}

# Threshold to unlock secondary exam (65%)
SECONDARY_UNLOCK_THRESHOLD = 0.65
# ============================================================
#  HELPER: total unseen questions remaining at a level
# ============================================================
def _questions_remaining(quiz, diff, answered_ids, phase='MAIN'):
    """Get remaining questions for a difficulty level in a specific phase"""
    if phase == 'MAIN':
        pool, fetch_diff = DB_POOL_MAIN[diff]
    else:
        pool, fetch_diff = DB_POOL_SECONDARY[diff]

    return QuizQuestion.objects.filter(
        quiz=quiz,
        difficulty=fetch_diff,
        pool=pool,
    ).exclude(question_id__in=answered_ids).count()


def _pick_question(quiz, diff, answered_ids, phase='MAIN'):
    """Pick question from appropriate phase pool"""
    if phase == 'MAIN':
        pool, fetch_diff = DB_POOL_MAIN[diff]
    else:
        pool, fetch_diff = DB_POOL_SECONDARY[diff]

    # Try PRIMARY first
    primary_qs = list(QuizQuestion.objects.filter(
        quiz=quiz,
        difficulty=fetch_diff,
        pool=pool,
        role=QuizQuestion.Role.PRIMARY,
    ).exclude(question_id__in=answered_ids).select_related('question'))

    if primary_qs:
        return random.choice(primary_qs).question, False

    # Fall back to BUFFER
    buffer_qs = list(QuizQuestion.objects.filter(
        quiz=quiz,
        difficulty=fetch_diff,
        pool=pool,
        role=QuizQuestion.Role.BUFFER,
    ).exclude(question_id__in=answered_ids).select_related('question'))

    if buffer_qs:
        return random.choice(buffer_qs).question, True

    return None, False


def _apply_buffer_penalty(session, diff, is_buffer, quiz, phase='MAIN'):
    """Apply buffer penalty based on phase"""
    if not is_buffer:
        return

    # Calculate threshold based on phase
    if phase == 'MAIN':
        max_possible = (
                quiz.easy_count * MAIN_MARKS['Easy'] +
                quiz.medium_count * MAIN_MARKS['Medium'] +
                quiz.hard_count * MAIN_MARKS['Hard']
        )
        current_score = session.main_running_score
        pool_field_map = MAIN_POOL_FIELD
    else:
        max_possible = (
                quiz.sec_easy_count * SECONDARY_MARKS['Easy'] +
                quiz.sec_medium_count * SECONDARY_MARKS['Medium'] +
                quiz.sec_hard_count * SECONDARY_MARKS['Hard']
        )
        current_score = session.secondary_running_score
        pool_field_map = SECONDARY_POOL_FIELD

    threshold = max_possible * 0.65

    if current_score >= threshold:
        return

    # Apply penalty
    if phase == 'MAIN':
        session.main_running_score += BUFFER_BORROW_PENALTY.get(diff, -1)
    else:
        session.secondary_running_score += BUFFER_BORROW_PENALTY.get(diff, -1)

    next_diff = NEXT_LEVEL.get(diff)
    if next_diff and next_diff in pool_field_map:
        field = pool_field_map[next_diff]
        setattr(session, field, max(0, getattr(session, field, 0) - 1))

# ============================================================
#  CORE: get_next_question
#  Called AFTER process_answer on every submission.
#  Handles pool exhaustion + fallback chain.
#  Mutates session but does NOT save — caller saves.
#
#  Returns:
#    (Question, False)  →  serve this question
#    (None, True)       →  terminate (nothing left anywhere)
# ============================================================
# def get_next_question(session, quiz):
#     answered_ids = list(session.responses.values_list('question_id', flat=True))
#     diff = session.current_difficulty
#
#     # --- Try current level ---
#     question, is_buffer = _pick_question(quiz, diff, answered_ids)
#     if question is not None:
#         _apply_buffer_penalty(session, diff, is_buffer)
#         return question, False
#
#     # --- Current level exhausted: walk DOWN the chain ---
#     idx = DIFFICULTY_ORDER.index(diff)
#     for fallback_diff in reversed(DIFFICULTY_ORDER[:idx]):
#         if _questions_remaining(quiz, fallback_diff, answered_ids) > 0:
#             # Demote to fallback level, reset both streaks
#             session.current_difficulty = fallback_diff
#             session.consecutive_correct = 0
#             session.consecutive_wrong = 0
#             question, is_buffer = _pick_question(quiz, fallback_diff, answered_ids)
#             if question is not None:
#                 _apply_buffer_penalty(session, fallback_diff, is_buffer)
#                 return question, False
#
#     # --- Nothing left anywhere ---
#     session.is_active = False
#     return None, True

def get_next_question(session, quiz, assessment):
    """Get next question based on current phase"""
    answered_ids = list(session.responses.values_list('question_id', flat=True))
    phase = assessment.current_phase

    # Select appropriate difficulty order and field
    if phase == 'MAIN':
        difficulty_order = MAIN_DIFFICULTY_ORDER
        diff = session.current_difficulty
    else:
        difficulty_order = SECONDARY_DIFFICULTY_ORDER
        diff = session.current_difficulty  # Will be reset when entering secondary

    # Try current level
    question, is_buffer = _pick_question(quiz, diff, answered_ids, phase)
    if question is not None:
        _apply_buffer_penalty(session, diff, is_buffer, quiz, phase)
        return question, False

    # Current level exhausted: walk DOWN the chain
    idx = difficulty_order.index(diff)
    for fallback_diff in reversed(difficulty_order[:idx]):
        if _questions_remaining(quiz, fallback_diff, answered_ids, phase) > 0:
            session.current_difficulty = fallback_diff
            session.consecutive_correct = 0
            session.consecutive_wrong = 0
            question, is_buffer = _pick_question(quiz, fallback_diff, answered_ids, phase)
            if question is not None:
                _apply_buffer_penalty(session, fallback_diff, is_buffer, quiz, phase)
                return question, False

    # Nothing left in current phase
    return None, True


def process_answer(session, is_correct, is_skipped, phase='MAIN'):
    """Process answer with phase-specific scoring"""
    diff = session.current_difficulty
    marks = MAIN_MARKS if phase == 'MAIN' else SECONDARY_MARKS
    difficulty_order = MAIN_DIFFICULTY_ORDER if phase == 'MAIN' else SECONDARY_DIFFICULTY_ORDER

    if is_correct and not is_skipped:
        # Add to appropriate running score
        if phase == 'MAIN':
            session.main_running_score += marks.get(diff, 0)
        else:
            session.secondary_running_score += marks.get(diff, 0)

        session.consecutive_correct += 1
        session.consecutive_wrong = 0

        # Promotion logic
        if session.consecutive_correct >= 2:
            idx = difficulty_order.index(diff)
            if idx < len(difficulty_order) - 1:
                new_diff = difficulty_order[idx + 1]
                session.current_difficulty = new_diff
                session.consecutive_correct = 0
                session.consecutive_wrong = 0
                if new_diff == 'Medium' and phase == 'MAIN':
                    session.is_gate_passed = True
                return 'promote'
        return 'stay'

    else:
        # Wrong/Skipped
        session.consecutive_wrong += 1
        session.consecutive_correct = 0

        # Demotion logic
        if session.consecutive_wrong >= 2:
            idx = difficulty_order.index(diff)
            if idx > 0:
                prev_diff = difficulty_order[idx - 1]
                penalty = STEPDOWN_PENALTY.get((diff, prev_diff), 0)

                if phase == 'MAIN':
                    session.main_running_score += penalty
                else:
                    session.secondary_running_score += penalty

                session.current_difficulty = prev_diff
                session.consecutive_correct = 0
                session.consecutive_wrong = 0
                return 'demote'
        return 'stay'


# ============================================================
#  HELPER: _complete_assessment
#  Single place to shut down a test — score, status, cleanup.
# ============================================================
def _check_secondary_unlock(assessment, session, quiz):
    """Check if candidate qualifies for secondary exam"""
    max_main = (
            quiz.easy_count * MAIN_MARKS['Easy'] +
            quiz.medium_count * MAIN_MARKS['Medium'] +
            quiz.hard_count * MAIN_MARKS['Hard']
    )

    main_percentage = (session.main_running_score / max_main) if max_main > 0 else 0

    return main_percentage >= SECONDARY_UNLOCK_THRESHOLD


def _complete_main_exam(assessment, session, quiz):
    """Complete main exam and check secondary unlock"""
    max_main = (
            quiz.easy_count * MAIN_MARKS['Easy'] +
            quiz.medium_count * MAIN_MARKS['Medium'] +
            quiz.hard_count * MAIN_MARKS['Hard']
    )

    assessment.main_exam_score = session.main_running_score  # Store raw marks
    assessment.main_exam_completed_at = timezone.now()

    # Check if secondary exam should be unlocked
    if _check_secondary_unlock(assessment, session, quiz):
        assessment.secondary_exam_unlocked = True
        assessment.current_phase = 'SECONDARY'

        # Reset adaptive parameters for fresh secondary session
        session.current_difficulty = 'Easy'
        session.consecutive_correct = 0
        session.consecutive_wrong = 0
        session.current_question = None

        session.save()
        assessment.save(update_fields=[
            'main_exam_score',
            'main_exam_completed_at',
            'secondary_exam_unlocked',
            'current_phase'
        ])

        return True  # Continue to secondary
    else:
        # Did not qualify for secondary - complete assessment
        session.is_active = False
        session.save()

        assessment.status = Assessment.Status.COMPLETED
        assessment.final_score = assessment.main_exam_score  # Only main score here
        assessment.save(update_fields=['status', 'final_score'])

        return False  # End assessment


def _complete_assessment(assessment, session, quiz):
    """Complete entire assessment (both phases if applicable)"""
    phase = assessment.current_phase

    if phase == 'MAIN':
        # Completing main exam
        return _complete_main_exam(assessment, session, quiz)

    else:
        # Completing secondary exam
        max_secondary = (
                quiz.sec_easy_count * SECONDARY_MARKS['Easy'] +
                quiz.sec_medium_count * SECONDARY_MARKS['Medium'] +
                quiz.sec_hard_count * SECONDARY_MARKS['Hard']
        )

        assessment.secondary_exam_score = session.secondary_running_score  # Store raw marks

        # Calculate combined final score (optional: you can weight them differently)
        assessment.final_score = assessment.main_exam_score  # Or combine both

        session.is_active = False
        session.current_question = None
        session.save()

        assessment.status = Assessment.Status.COMPLETED
        assessment.save(update_fields=['status', 'final_score', 'secondary_exam_score'])

        return False  # End assessment


# ============================================================
#  VIEW 1: take_assessment
# ============================================================
def start_assessment(request, token):
    assessment = get_object_or_404(Assessment, magic_link_token=token)

    if assessment.status == Assessment.Status.NOT_STARTED:
        assessment.status = Assessment.Status.IN_PROGRESS
        assessment.started_at = timezone.now()
        assessment.save()

    return redirect('take_assessment', token=token)


def take_assessment(request, token):
    assessment = get_object_or_404(
        Assessment.objects.select_related('quiz', 'candidate', 'session'),
        magic_link_token=token
    )

    # Completion
    if assessment.status == Assessment.Status.COMPLETED:
        return render(request, 'quiz_complete.html', {
            'assessment': assessment,
            'main_score': assessment.main_exam_score,
            'secondary_score': assessment.secondary_exam_score,
            'qualified_for_secondary': assessment.secondary_exam_unlocked,
        })

    # Time check
    if assessment.is_time_up:
        _complete_assessment(assessment, assessment.session, assessment.quiz)
        return render(request, 'quiz_complete.html', {
            'assessment': assessment,
            'reason': 'time_up',
            'main_score': assessment.main_exam_score,
            'secondary_score': assessment.secondary_exam_score,
        })

    # Landing page
    if assessment.status == Assessment.Status.NOT_STARTED:
        return render(request, 'quiz_landing.html', {
            'assessment': assessment,
            'token': token
        })

    # Active exam logic
    session = assessment.session
    quiz = assessment.quiz
    phase = assessment.current_phase

    if not session.is_active:
        _complete_assessment(assessment, session, quiz)
        return render(request, 'quiz_complete.html', {'assessment': assessment})

    # Lock current question
    if session.current_question is None:
        question, terminated = get_next_question(session, quiz, assessment)

        if terminated:
            # Phase completed
            if phase == 'MAIN':
                continued = _complete_main_exam(assessment, session, quiz)
                if continued:
                    # Redirect to show secondary exam intro
                    return render(request, 'secondary_exam_intro.html', {
                        'assessment': assessment,
                        'main_score': assessment.main_exam_score,
                        'token': token,
                    })
                else:
                    return render(request, 'quiz_complete.html', {
                        'assessment': assessment,
                        'reason': 'did_not_qualify',
                        'main_score': assessment.main_exam_score,
                    })
            else:
                _complete_assessment(assessment, session, quiz)
                return render(request, 'quiz_complete.html', {'assessment': assessment})

        session.current_question = question
        session.save()
    else:
        question = session.current_question

    # Calculate progress based on phase
    if phase == 'MAIN':
        total_limit = quiz.easy_count + quiz.medium_count + quiz.hard_count
        q_answered = session.main_q_answered
    else:
        total_limit = quiz.sec_easy_count + quiz.sec_medium_count + quiz.sec_hard_count
        q_answered = session.secondary_q_answered

    time_remaining = None
    if assessment.started_at:
        elapsed = (timezone.now() - assessment.started_at).total_seconds()
        time_remaining = max(0, int(assessment.test_duration_mins * 60 - elapsed))



    return render(request, 'take_assessment.html', {
        'assessment': assessment,
        'session': session,
        'question': question,
        'options': question.options.all(),
        'progress_pct': int((q_answered / total_limit) * 100) if total_limit else 0,
        'time_remaining': time_remaining,
        'q_number': q_answered + 1,
        'total': total_limit,
        'token': token,
        'current_phase': phase,
        'current_score': session.main_running_score if phase == 'MAIN' else session.secondary_running_score,

        'phase_display': 'Main Exam' if phase == 'MAIN' else 'Secondary Exam',
    })


@transaction.atomic
def submit_answer(request, token):
    if request.method != 'POST':
        return redirect('take_assessment', token=token)

    assessment = get_object_or_404(
        Assessment.objects.select_related('quiz', 'session'),
        magic_link_token=token
    )

    if assessment.status == Assessment.Status.COMPLETED:
        return redirect('take_assessment', token=token)

    if assessment.is_time_up:
        _complete_assessment(assessment, assessment.session, assessment.quiz)
        return redirect('take_assessment', token=token)

    session = assessment.session
    quiz = assessment.quiz
    phase = assessment.current_phase
    question = session.current_question

    if question is None:
        return redirect('take_assessment', token=token)

    # Evaluate answer (same as before)
    is_skipped = 'skip' in request.POST
    is_correct = False
    selected_options = []
    typed_answer = None

    if not is_skipped:
        if question.type in ('MCQ', 'MSQ'):
            selected_options = list(QuestionOption.objects.filter(
                id__in=request.POST.getlist('options'),
                question=question
            ))
            correct_ids = set(
                question.options.filter(is_correct=True).values_list('id', flat=True)
            )
            is_correct = {o.id for o in selected_options} == correct_ids

        elif question.type == 'One-Word':
            typed_answer = request.POST.get('typed_answer', '').strip()
            correct_opt = question.options.filter(is_correct=True).first()
            is_correct = (
                    correct_opt is not None and
                    typed_answer.lower() == correct_opt.option_text.strip().lower()
            )

    # Save response
    resp = Response.objects.create(
        test_session=session,
        question=question,
        is_correct=is_correct,
        is_skipped=is_skipped,
        typed_answer=typed_answer,
    )
    if selected_options:
        resp.selected_options.set(selected_options)

    # Process answer with phase context
    process_answer(session, is_correct, is_skipped, phase)

    # Increment phase-specific counters
    if phase == 'MAIN':
        session.main_q_answered += 1
        phase_limit = quiz.easy_count + quiz.medium_count + quiz.hard_count
        q_answered = session.main_q_answered
    else:
        session.secondary_q_answered += 1
        phase_limit = quiz.sec_easy_count + quiz.sec_medium_count + quiz.sec_hard_count
        q_answered = session.secondary_q_answered

    session.total_q_answered += 1
    assessment.current_question_index += 1

    # Check phase completion
    if q_answered >= phase_limit:
        if phase == 'MAIN':
            continued = _complete_main_exam(assessment, session, quiz)
            if not continued:
                return redirect('take_assessment', token=token)
            # If continued, fall through to get first secondary question
        else:
            _complete_assessment(assessment, session, quiz)
            return redirect('take_assessment', token=token)

    # Get next question
    next_question, terminated = get_next_question(session, quiz, assessment)

    if terminated:
        if phase == 'MAIN':
            _complete_main_exam(assessment, session, quiz)
        else:
            _complete_assessment(assessment, session, quiz)
    else:
        session.current_question = next_question
        session.save()
        assessment.save(update_fields=['current_question_index'])

    return redirect('take_assessment', token=token)