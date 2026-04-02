import json
import traceback  # Added for detailed error tracking
import google.generativeai as genai
from django.conf import settings
from .models import JobLevel, Question, QuestionOption

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel('models/gemini-3-flash-preview')


def generate_questions_by_difficulty(level, difficulty, count=25):
    """Helper function to call AI for a specific difficulty batch"""

    print(f"--- Starting AI Generation for {level.level_name} | {difficulty} ---")

    prompt = f"""
    You are an expert Technical Interviewer. Generate exactly {count} unique {difficulty} questions 
    based on the following Job Description for a {level.level_name} role in {level.job.name}.

    STRICT JSON FORMAT:
    {{
      "questions": [
        {{
          "type": "MCQ", 
          "question_prompt": "Your question here",
          "options": [
            {{"option_text": "Correct Answer", "is_correct": true}},
            {{"option_text": "Wrong Answer 1", "is_correct": false}},
            {{"option_text": "Wrong Answer 2", "is_correct": false}},
            {{"option_text": "Wrong Answer 3", "is_correct": false}}
          ]
        }}
      ]
    }}

    MIX TYPES: MCQ (1 correct), MSQ (2+ correct), and One-Word (Short answer).
    Job Description: {level.jd_text}
    """

    try:
        response = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json"}
        )

        # Log the raw response text if you suspect JSON issues
        # print(f"DEBUG: Raw AI Response: {response.text}")

        data = json.loads(response.text)
        questions_list = data.get("questions", [])

        print(f"AI returned {len(questions_list)} questions.")

        for i, q_data in enumerate(questions_list):
            try:
                new_q = Question.objects.create(
                    job_level=level,
                    type=q_data.get("type", "MCQ"),
                    difficulty=difficulty,
                    question_prompt=q_data.get("question_prompt", "Missing Prompt")
                )

                for opt_data in q_data.get("options", []):
                    QuestionOption.objects.create(
                        question=new_q,
                        option_text=opt_data.get("option_text", ""),
                        is_correct=opt_data.get("is_correct", False)
                    )

                print(f"  [{i + 1}/{len(questions_list)}] Saved: {new_q.question_prompt[:50]}...")

            except Exception as inner_e:
                print(f"  ❌ Error saving individual question {i + 1}: {inner_e}")
                continue

    except json.JSONDecodeError as json_e:
        print(f"❌ JSON Parsing Error: The AI sent invalid JSON. Error: {json_e}")
        print(f"Raw Response Content: {response.text}")
        raise json_e
    except Exception as e:
        print(f"❌ Error in generate_questions_by_difficulty: {e}")
        traceback.print_exc()  # This shows the exact line number where it failed
        raise e


def generate_quiz_for_level(level_id):
    """Main service called by the view"""
    try:
        level = JobLevel.objects.get(id=level_id)

        # Batch 1: Easy
        generate_questions_by_difficulty(level, "Easy", 25)

        # Batch 2: Medium
        generate_questions_by_difficulty(level, "Medium", 25)

        # Batch 3: Hard
        generate_questions_by_difficulty(level, "Hard", 25)

        print("✅ FULL QUIZ GENERATION SUCCESSFUL")
        return True

    except JobLevel.DoesNotExist:
        print(f"❌ Error: JobLevel with ID {level_id} not found.")
        return False
    except Exception as e:
        print(f"❌ FATAL AI SERVICE ERROR: {e}")
        traceback.print_exc()
        return False