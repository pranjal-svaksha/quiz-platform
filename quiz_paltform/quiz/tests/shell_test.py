# ============================================================
#  DJANGO SHELL SIMULATION SCRIPT
#  Run with: python manage.py shell < shell_test.py
#  Or paste blocks one by one in: python manage.py shell
# ============================================================

import random
from django.utils import timezone
from quiz.models import (
    Job, JobLevel, Question, QuestionOption,
    Quiz, Candidate, Assessment, TestSession, QuizQuestion
)
from quiz.views import process_answer, get_next_question, _complete_assessment

# ============================================================
#  STEP 1: Grab an existing finalized quiz
# ============================================================
quiz = Quiz.objects.filter(is_finalized=True).first()
if not quiz:
    print("ERROR: No finalized quiz found. Finalize a quiz first.")
else:
    print(f"Using quiz: {quiz.title}")
    print(f"  Easy: {quiz.easy_count}, Medium: {quiz.medium_count}, Hard: {quiz.hard_count}, Secondary: {quiz.secondary_exam_count}")
    print(f"  QuizQuestions saved: {quiz.quiz_questions.count()}")


# ============================================================
#  STEP 2: Create a test candidate + assessment + session
# ============================================================
def create_test_session(quiz, candidate_name="Shell Tester"):
    candidate, _ = Candidate.objects.get_or_create(
        email=f"{candidate_name.lower().replace(' ', '')}@shelltest.com",
        defaults={'name': candidate_name}
    )
    import uuid
    assessment = Assessment.objects.create(
        quiz=quiz,
        candidate=candidate,
        magic_link_token=str(uuid.uuid4()),
        test_duration_mins=60,
        status=Assessment.Status.IN_PROGRESS,
        started_at=timezone.now(),
    )
    session = TestSession.objects.create(
        assessment=assessment,
        easy_pool=quiz.easy_count,
        medium_pool=quiz.medium_count,
        hard_pool=quiz.hard_count,
        current_difficulty='Easy',
    )
    print(f"\nCreated assessment: {assessment.id}")
    print(f"Session: {session.id} | Difficulty: {session.current_difficulty} | Score: {session.running_score}")
    return assessment, session


# ============================================================
#  STEP 3: Helper to simulate answering one question
# ============================================================
def answer_question(session, quiz, is_correct, label=""):
    question, terminated = get_next_question(session, quiz)
    if terminated:
        print(f"  [{label}] TERMINATED — no questions left")
        return False
    if question is None:
        print(f"  [{label}] Quiz limit reached")
        return False

    session.current_question = question
    session.save()

    # Create a fake Response
    from quiz.models import Response
    Response.objects.create(
        test_session=session,
        question=question,
        is_correct=is_correct,
        is_skipped=False,
    )

    result = process_answer(session, is_correct=is_correct, is_skipped=False)
    session.total_q_answered += 1
    session.save()

    print(f"  [{label}] Q{session.total_q_answered}: {question.difficulty} | "
          f"correct={is_correct} | result={result} | "
          f"now={session.current_difficulty} | "
          f"score={session.running_score} | "
          f"streak C={session.consecutive_correct} W={session.consecutive_wrong}")
    return True


# ============================================================
#  SCENARIO 1: Promote — 2 consecutive correct at Easy → Medium
# ============================================================
print("\n" + "="*60)
print("SCENARIO 1: Promote Easy → Medium")
print("="*60)
assessment, session = create_test_session(quiz, "Promote Tester")
answer_question(session, quiz, is_correct=True,  label="Q1 correct")
answer_question(session, quiz, is_correct=True,  label="Q2 correct → PROMOTE")
print(f"  Expected: Medium | Got: {session.current_difficulty}")
assessment.delete()


# ============================================================
#  SCENARIO 2: Demote — 2 consecutive wrong at Medium → Easy
# ============================================================
print("\n" + "="*60)
print("SCENARIO 2: Demote Medium → Easy")
print("="*60)
assessment, session = create_test_session(quiz, "Demote Tester")
# Force to Medium first
session.current_difficulty = 'Medium'
session.save()
answer_question(session, quiz, is_correct=False, label="Q1 wrong")
answer_question(session, quiz, is_correct=False, label="Q2 wrong → DEMOTE")
print(f"  Expected: Easy | Got: {session.current_difficulty}")
assessment.delete()


# ============================================================
#  SCENARIO 3: Alternating — stays at same level
# ============================================================
print("\n" + "="*60)
print("SCENARIO 3: Alternating right-wrong (should stay at Easy)")
print("="*60)
assessment, session = create_test_session(quiz, "Alternating Tester")
for i in range(6):
    is_correct = (i % 2 == 0)
    answer_question(session, quiz, is_correct=is_correct, label=f"Q{i+1}")
print(f"  Expected: Easy throughout | Final: {session.current_difficulty}")
assessment.delete()


# ============================================================
#  SCENARIO 4: Full promote chain Easy→Medium→Hard→Secondary
# ============================================================
print("\n" + "="*60)
print("SCENARIO 4: Full promote chain")
print("="*60)
assessment, session = create_test_session(quiz, "Full Promote Tester")
for i in range(8):
    answer_question(session, quiz, is_correct=True, label=f"Q{i+1}")
print(f"  Expected: Secondary | Got: {session.current_difficulty}")
assessment.delete()


# ============================================================
#  SCENARIO 5: Quiz limit — stops at 25 questions
# ============================================================
print("\n" + "="*60)
print("SCENARIO 5: Quiz limit (answer all 25)")
print("="*60)
assessment, session = create_test_session(quiz, "Limit Tester")
for i in range(30):  # try more than 25
    if session.total_q_answered >= quiz.total_questions_limit:
        print(f"  Stopped at Q{session.total_q_answered} — limit reached correctly")
        break
    ok = answer_question(session, quiz, is_correct=True, label=f"Q{i+1}")
    if not ok:
        break
assessment.delete()


# ============================================================
#  SCENARIO 6: Pool exhaustion + fallback
# ============================================================
print("\n" + "="*60)
print("SCENARIO 6: Pool exhaustion — force Medium, exhaust it, expect fallback to Easy")
print("="*60)
assessment, session = create_test_session(quiz, "Exhaustion Tester")
session.current_difficulty = 'Medium'
session.medium_pool = 1   # only 1 primary question left
session.save()
# Answer enough to exhaust medium
for i in range(10):
    ok = answer_question(session, quiz, is_correct=False, label=f"Q{i+1}")
    if not ok or not session.is_active:
        break
print(f"  Final difficulty: {session.current_difficulty} | Active: {session.is_active}")
assessment.delete()


# ============================================================
#  SCENARIO 7: Score tracking
# ============================================================
print("\n" + "="*60)
print("SCENARIO 7: Score tracking")
print("="*60)
assessment, session = create_test_session(quiz, "Score Tester")
# 2 correct Easy (+1 each) → promote to Medium
answer_question(session, quiz, is_correct=True,  label="+1 easy")
answer_question(session, quiz, is_correct=True,  label="+1 easy → promote")
# 2 wrong Medium → demote (-1 penalty) + 2 wrong = demote
answer_question(session, quiz, is_correct=False, label="wrong medium")
answer_question(session, quiz, is_correct=False, label="wrong medium → demote -1")
print(f"  Expected score: +1+1-1 = 1 | Got: {session.running_score}")
assessment.delete()

print("\n" + "="*60)
print("ALL SHELL TESTS COMPLETE")
print("="*60)