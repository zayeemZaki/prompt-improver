import json
import os
import time
from sqlalchemy.orm import Session
import google.generativeai as genai
from database import SessionLocal, PromptVersion, TestCase, EvaluationResult, Prompt
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

def get_db():
    return SessionLocal()

def run_deterministic_checks(output: str, expected: str) -> dict:
    metrics = {"score_penalty": 0, "flags": []}
    if not output.strip():
        metrics["score_penalty"] += 100
        metrics["flags"].append("empty_output")
        return metrics
    if len(output) > 500:
        metrics["score_penalty"] += 10
        metrics["flags"].append("too_long")
    return metrics

def ai_judge(prediction: str, expected: str) -> dict:
    judge_prompt = f"""
        You are an impartial judge.
        GROUND TRUTH: "{expected}"
        MODEL OUTPUT: "{prediction}"
        
        Compare them. Return valid JSON:
        {{ "reasoning": "...", "score": 85 }}
    """
    try:
        response = model.generate_content(judge_prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except:
        return {"score": 0, "reasoning": "Error parsing judge response"}

def run_evaluation(prompt_slug: str):
    session = get_db()
    prompt = session.query(Prompt).filter_by(slug=prompt_slug).first()
    
    if not prompt or not prompt.versions:
        print("Prompt or versions not found.")
        session.close()
        return

    latest_version = max(prompt.versions, key=lambda v: v.version_number)
    
    test_cases = session.query(TestCase).filter_by(prompt_id=prompt.id).all()
    
    if not test_cases:
        print("No test cases found. Generate them first!")
        session.close()
        return
    
    print(f"Evaluating v{latest_version.version_number} on {len(test_cases)} cases...")

    total_score = 0
    pass_count = 0
    fail_count = 0
    failures = []

    for case in test_cases:
        try:
            input_dict = json.loads(case.input_data) if isinstance(case.input_data, str) else case.input_data
        except:
            input_dict = {"article": case.input_data}

        prompt_text = latest_version.template_text
        
        if isinstance(input_dict, dict):
            for key, value in input_dict.items():
                prompt_text = prompt_text.replace(f"{{{{{key}}}}}", str(value))
        else:
            prompt_text = prompt_text.replace("{{article}}", str(input_dict))
            
        try:
            response = model.generate_content(prompt_text)
            output = response.text.strip()
        except Exception as e:
            print(f"Error generating content: {e}")
            output = ""

        det_metrics = run_deterministic_checks(output, case.expected_output)
        judge_result = ai_judge(output, case.expected_output)
        final_score = max(0, judge_result['score'] - det_metrics['score_penalty'])
        
        total_score += final_score
        
        if final_score >= 90:
            pass_count += 1
        else:
            fail_count += 1
            failures.append({
                "input": input_dict,
                "expected": case.expected_output,
                "actual": output,
                "judge_reasoning": judge_result['reasoning']
            })

    avg_score = total_score / len(test_cases)
    
    result = EvaluationResult(
        version_id=latest_version.id,
        score=avg_score,
        pass_count=pass_count,
        fail_count=fail_count,
        detailed_metrics={"failures": failures} 
    )
    session.add(result)
    session.commit()
    
    print(f"Eval Complete! Score: {avg_score:.1f}% (Failures: {len(failures)})")
    session.close()
    return avg_score, failures

if __name__ == "__main__":
    run_evaluation("news-summarizer")