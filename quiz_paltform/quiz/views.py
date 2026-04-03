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
from django.db.models import Count, Min


# Add this temporary diagnostic view to help identify field names

def diagnostic_model_fields(request):
    """
    Temporary diagnostic view to check your actual model field names.
    Access at: /quiz/diagnostic/
    """
    from django.http import HttpResponse

    # Get a sample question
    sample_question = Question.objects.first()

    if not sample_question:
        return HttpResponse("No questions in database. Add some questions first.")

    # Get field names
    question_fields = [f.name for f in Question._meta.get_fields()]

    # Get sample option if exists
    sample_option = sample_question.options.first() if hasattr(sample_question, 'options') else None
    option_fields = [f.name for f in sample_option._meta.model._meta.get_fields()] if sample_option else []

    # Build diagnostic output
    output = []
    output.append("<h1>Model Field Diagnostic</h1>")
    output.append("<h2>Question Model Fields:</h2>")
    output.append("<ul>")
    for field in question_fields:
        output.append(f"<li><strong>{field}</strong></li>")
    output.append("</ul>")

    output.append("<h2>Sample Question Data:</h2>")
    output.append("<pre>")
    for field in question_fields:
        try:
            value = getattr(sample_question, field)
            output.append(f"{field}: {value}\n")
        except:
            output.append(f"{field}: [relationship field]\n")
    output.append("</pre>")

    if sample_option:
        output.append("<h2>Option Model Fields:</h2>")
        output.append("<ul>")
        for field in option_fields:
            output.append(f"<li><strong>{field}</strong></li>")
        output.append("</ul>")

        output.append("<h2>Sample Option Data:</h2>")
        output.append("<pre>")
        for field in option_fields:
            try:
                value = getattr(sample_option, field)
                output.append(f"{field}: {value}\n")
            except:
                output.append(f"{field}: [relationship field]\n")
        output.append("</pre>")

    output.append("<hr>")
    output.append("<h2>What to look for:</h2>")
    output.append("<p><strong>Question text field is probably one of these:</strong></p>")
    output.append("<ul>")
    output.append("<li><code>text</code></li>")
    output.append("<li><code>question_text</code></li>")
    output.append("<li><code>question_prompt</code></li>")
    output.append("<li><code>prompt</code></li>")
    output.append("</ul>")

    output.append("<p><strong>Option text field is probably one of these:</strong></p>")
    output.append("<ul>")
    output.append("<li><code>text</code></li>")
    output.append("<li><code>option_text</code></li>")
    output.append("</ul>")

    return HttpResponse("\n".join(output))


# Add to urls.py:
# path('quiz/diagnostic/', views.diagnostic_model_fields, name='diagnostic_model_fields'),

def custom_404_view(request, exception=None):
    return render(request, '404.html', status=404)

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


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
import random
import json

# ============================================================================
# CONFIGURATION: How many extra questions to show beyond requirements
# ============================================================================
PREVIEW_MULTIPLIER = 2.0  # Show 2x the required questions (e.g., need 10 -> show 20)


# ============================================================================
# PHASE 1: CREATE QUIZ (Same as before)
# ============================================================================

def create_quiz(request):
    levels = JobLevel.objects.all().select_related('job')

    if request.method == "POST":
        title = request.POST.get('title')
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

        # Define Pools
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

        # Validation Logic: Secondary
        is_same_pool = not s_level_ids or set(p_level_ids) == set(s_level_ids)

        for diff, req, p_req in [('Easy', se_e, e_q), ('Medium', se_m, m_q), ('Hard', se_h, h_q)]:
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

        # Set ManyToMany relationships
        new_quiz.primary_job_levels.set(p_level_ids)
        if s_level_ids:
            new_quiz.secondary_job_levels.set(s_level_ids)

        messages.success(request, f"Quiz '{title}' created successfully!")
        return redirect('view_quiz_questions', quiz_id=new_quiz.id)

    return render(request, 'create_quiz.html', {'levels': levels})


# ============================================================================
# PHASE 2: VIEW QUESTIONS WITH MANUAL SELECTION
# ============================================================================

def view_quiz_questions(request, quiz_id):
    """
    Main view for question selection:
    - If finalized: show locked questions from DB
    - If not finalized: show expanded pool with pre-selected defaults
    """
    quiz = get_object_or_404(
        Quiz.objects.prefetch_related('primary_job_levels', 'secondary_job_levels'),
        id=quiz_id
    )

    # --- FINALIZED: Show saved questions ---
    if quiz.is_finalized:
        saved_qs = QuizQuestion.objects.filter(quiz=quiz).select_related(
            'question'
        ).prefetch_related('question__options')

        finalized_data = {
            'Primary': {'Easy': [], 'Medium': [], 'Hard': []},
            'Secondary': {'Easy': [], 'Medium': [], 'Hard': []}
        }

        for qq in saved_qs:
            pool_key = 'Secondary' if qq.pool == 'secondary' else 'Primary'
            finalized_data[pool_key][qq.difficulty].append({
                'question': qq.question,
                'role': qq.role.upper()  # converts 'primary' → 'PRIMARY', 'buffer' → 'BUFFER'
            })

        return render(request, 'view_quiz_questions.html', {
            'quiz': quiz,
            'is_finalized': True,
            'finalized_data': finalized_data,
        })

    # --- NOT FINALIZED: Show selection interface ---

    # Get level IDs
    p_level_ids = list(quiz.primary_job_levels.values_list('id', flat=True))
    s_level_ids = list(quiz.secondary_job_levels.values_list('id', flat=True))
    if not s_level_ids:
        s_level_ids = p_level_ids

    # Check if selections already exist in session
    session_key = f'quiz_{quiz_id}_selections'
    saved_selections = request.session.get(session_key)

    # Build available questions and pre-selections
    primary_data = _build_selection_data(
        level_ids=p_level_ids,
        counts={
            'Easy': quiz.easy_count,
            'Medium': quiz.medium_count,
            'Hard': quiz.hard_count
        },
        pool_name='primary',
        saved_selections=saved_selections.get('primary') if saved_selections else None,
        exclude_ids=[]
    )

    # For secondary pool, exclude questions already used in primary
    used_primary_ids = []
    if saved_selections and 'primary' in saved_selections:
        for diff_data in saved_selections['primary'].values():
            used_primary_ids.extend(diff_data.get('primary', []))
            used_primary_ids.extend(diff_data.get('buffer', []))

    secondary_data = _build_selection_data(
        level_ids=s_level_ids,
        counts={
            'Easy': quiz.sec_easy_count,
            'Medium': quiz.sec_medium_count,
            'Hard': quiz.sec_hard_count
        },
        pool_name='secondary',
        saved_selections=saved_selections.get('secondary') if saved_selections else None,
        exclude_ids=used_primary_ids
    )
    print("PRIMARY DATA:", {
        diff: {
            'count': len(data['available']),
            'sel_primary': data['selected_primary'],
            'sel_buffer': data['selected_buffer'],
        }
        for diff, data in primary_data.items()
    })
    context = {
        'quiz': quiz,
        'is_finalized': False,
        'primary_data': primary_data,
        'secondary_data': secondary_data,
        'has_saved_selections': saved_selections is not None
    }

    return render(request, 'view_quiz_questions.html', context)


def _build_selection_data(level_ids, counts, pool_name, saved_selections=None, exclude_ids=None):
    """
    Helper to build question selection data for a pool.

    Returns structure:
    {
        'Easy': {
            'required_primary': 5,
            'required_buffer': 5,
            'available': [Q1, Q2, Q3, ...],  # Expanded pool (2x required)
            'selected_primary': [id1, id2, ...],  # Pre-selected or saved
            'selected_buffer': [id6, id7, ...]
        },
        'Medium': {...},
        'Hard': {...}
    }
    """
    if exclude_ids is None:
        exclude_ids = []

    result = {}

    for difficulty, count in counts.items():
        if count == 0:
            continue

        required_total = count * 2  # Primary + Buffer
        show_count = max(int(required_total * PREVIEW_MULTIPLIER), required_total + 5)

        # Fetch available questions
        available_qs = list(
            Question.objects.filter(
                job_level_id__in=level_ids,
                difficulty=difficulty
            ).exclude(
                id__in=exclude_ids
            ).prefetch_related('options')[:show_count]
        )

        # Use saved selections if they exist
        if saved_selections and difficulty in saved_selections:
            selected_primary = saved_selections[difficulty].get('primary', [])
            selected_buffer = saved_selections[difficulty].get('buffer', [])
        else:
            # Pre-select random questions as defaults
            if len(available_qs) >= required_total:
                shuffled = available_qs.copy()
                random.shuffle(shuffled)
                selected_primary = [q.id for q in shuffled[:count]]
                selected_buffer = [q.id for q in shuffled[count:required_total]]
            else:
                # Not enough questions - select what's available
                selected_primary = [q.id for q in available_qs[:count]]
                selected_buffer = [q.id for q in available_qs[count:required_total]]

        result[difficulty] = {
            'required_primary': count,
            'required_buffer': count,
            'available': available_qs,
            'selected_primary': selected_primary,
            'selected_buffer': selected_buffer,
        }

    return result


# ============================================================================
# PHASE 3: SAVE SELECTIONS TO SESSION
# ============================================================================

def save_quiz_selections(request, quiz_id):
    """
    AJAX endpoint to save user's manual question selections to session.

    Expected POST data:
    {
        "primary": {
            "Easy": {"primary": [1,2,3], "buffer": [4,5,6]},
            "Medium": {...},
            "Hard": {...}
        },
        "secondary": {
            "Easy": {...},
            ...
        }
    }
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    quiz = get_object_or_404(Quiz, id=quiz_id)

    if quiz.is_finalized:
        return JsonResponse({'success': False, 'error': 'Quiz already finalized'}, status=400)

    try:
        selections = json.loads(request.body)

        # Validate selections
        validation_result = _validate_selections(quiz, selections)
        if not validation_result['valid']:
            return JsonResponse({
                'success': False,
                'error': validation_result['error']
            }, status=400)

        # Save to session
        session_key = f'quiz_{quiz_id}_selections'
        request.session[session_key] = selections
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'message': 'Selections saved successfully!'
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def _validate_selections(quiz, selections):
    """
    Validate that selections meet requirements:
    - Correct counts for each difficulty
    - No duplicate IDs across pools/roles
    - All IDs are valid questions
    """
    # Check structure
    if 'primary' not in selections or 'secondary' not in selections:
        return {'valid': False, 'error': 'Missing primary or secondary selections'}

    all_selected_ids = []

    # Validate Primary
    primary_requirements = {
        'Easy': quiz.easy_count,
        'Medium': quiz.medium_count,
        'Hard': quiz.hard_count
    }

    for diff, required_count in primary_requirements.items():
        if required_count == 0:
            continue

        if diff not in selections['primary']:
            return {'valid': False, 'error': f'Missing Primary {diff} selections'}

        primary_ids = selections['primary'][diff].get('primary', [])
        buffer_ids = selections['primary'][diff].get('buffer', [])

        if len(primary_ids) != required_count:
            return {'valid': False, 'error': f'Primary {diff}: need {required_count} primary, got {len(primary_ids)}'}

        if len(buffer_ids) != required_count:
            return {'valid': False, 'error': f'Primary {diff}: need {required_count} buffer, got {len(buffer_ids)}'}

        all_selected_ids.extend(primary_ids)
        all_selected_ids.extend(buffer_ids)

    # Validate Secondary
    secondary_requirements = {
        'Easy': quiz.sec_easy_count,
        'Medium': quiz.sec_medium_count,
        'Hard': quiz.sec_hard_count
    }

    for diff, required_count in secondary_requirements.items():
        if required_count == 0:
            continue

        if diff not in selections['secondary']:
            return {'valid': False, 'error': f'Missing Secondary {diff} selections'}

        primary_ids = selections['secondary'][diff].get('primary', [])
        buffer_ids = selections['secondary'][diff].get('buffer', [])

        if len(primary_ids) != required_count:
            return {'valid': False, 'error': f'Secondary {diff}: need {required_count} primary, got {len(primary_ids)}'}

        if len(buffer_ids) != required_count:
            return {'valid': False, 'error': f'Secondary {diff}: need {required_count} buffer, got {len(buffer_ids)}'}

        all_selected_ids.extend(primary_ids)
        all_selected_ids.extend(buffer_ids)

    # Check for duplicates
    if len(all_selected_ids) != len(set(all_selected_ids)):
        return {'valid': False, 'error': 'Duplicate questions selected across pools/roles'}

    # Verify all IDs exist in database
    existing_count = Question.objects.filter(id__in=all_selected_ids).count()
    if existing_count != len(all_selected_ids):
        return {'valid': False, 'error': 'Some selected question IDs are invalid'}

    return {'valid': True}


# ============================================================================
# PHASE 4: FINALIZE WITH SAVED SELECTIONS
# ============================================================================

@transaction.atomic
def finalize_quiz_questions(request, quiz_id):
    """
    Finalize quiz using manually selected questions from session.
    """
    if request.method != "POST":
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    quiz = get_object_or_404(Quiz, id=quiz_id)

    if quiz.is_finalized:
        messages.warning(request, 'Quiz is already finalized.')
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    # Get selections from session
    session_key = f'quiz_{quiz_id}_selections'
    selections = request.session.get(session_key)

    if not selections:
        messages.error(request, 'No selections found. Please select questions first.')
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    # Validate one more time
    validation_result = _validate_selections(quiz, selections)
    if not validation_result['valid']:
        messages.error(request, f'Invalid selections: {validation_result["error"]}')
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    # Save to database
    _save_selections_to_db(quiz, selections)

    # Mark as finalized
    quiz.is_finalized = True
    quiz.save()

    # Clear session data
    if session_key in request.session:
        del request.session[session_key]

    messages.success(request, f"Quiz '{quiz.title}' has been finalized with your selected questions!")
    return redirect('view_quiz_questions', quiz_id=quiz_id)


def _save_selections_to_db(quiz, selections):
    """
    Save manually selected questions to QuizQuestion join table.
    """
    # Save Primary Pool
    for difficulty in ['Easy', 'Medium', 'Hard']:
        if difficulty not in selections['primary']:
            continue

        primary_ids = selections['primary'][difficulty]['primary']
        buffer_ids = selections['primary'][difficulty]['buffer']

        # Save primary role
        for q_id in primary_ids:
            QuizQuestion.objects.create(
                quiz=quiz,
                question_id=q_id,
                difficulty=difficulty,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                role=QuizQuestion.Role.PRIMARY
            )

        # Save buffer role
        for q_id in buffer_ids:
            QuizQuestion.objects.create(
                quiz=quiz,
                question_id=q_id,
                difficulty=difficulty,
                pool=QuizQuestion.Pool.PRIMARY_POOL,
                role=QuizQuestion.Role.BUFFER
            )

    # Save Secondary Pool
    for difficulty in ['Easy', 'Medium', 'Hard']:
        if difficulty not in selections['secondary']:
            continue

        primary_ids = selections['secondary'][difficulty]['primary']
        buffer_ids = selections['secondary'][difficulty]['buffer']

        # Save primary role
        for q_id in primary_ids:
            QuizQuestion.objects.create(
                quiz=quiz,
                question_id=q_id,
                difficulty=difficulty,
                pool=QuizQuestion.Pool.SECONDARY_POOL,
                role=QuizQuestion.Role.PRIMARY
            )

        # Save buffer role
        for q_id in buffer_ids:
            QuizQuestion.objects.create(
                quiz=quiz,
                question_id=q_id,
                difficulty=difficulty,
                pool=QuizQuestion.Pool.SECONDARY_POOL,
                role=QuizQuestion.Role.BUFFER
            )


# ============================================================================
# PHASE 5: CLEAR SELECTIONS (Optional - reset to defaults)
# ============================================================================

def clear_quiz_selections(request, quiz_id):
    """
    Clear saved selections and return to default pre-selected state.
    """
    quiz = get_object_or_404(Quiz, id=quiz_id)

    if quiz.is_finalized:
        messages.warning(request, 'Cannot clear selections - quiz is finalized.')
        return redirect('view_quiz_questions', quiz_id=quiz_id)

    session_key = f'quiz_{quiz_id}_selections'
    if session_key in request.session:
        del request.session[session_key]
        messages.success(request, 'Selections cleared. Defaults reloaded.')

    return redirect('view_quiz_questions', quiz_id=quiz_id)

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
        assessment.save(update_fields=['status', 'final_score', 'main_exam_score', 'main_exam_completed_at'])

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
        assessment.final_score = assessment.main_exam_score + session.secondary_running_score # Or combine both

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