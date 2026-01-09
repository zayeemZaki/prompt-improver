import concurrent.futures
import json
import os
import re
from typing import Any, Dict, List, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

from database import EvaluationResult, Prompt, SessionLocal, TestCase

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
JUDGE_MODEL = genai.GenerativeModel("gemini-2.5-flash-lite")
GENERATION_MODEL = genai.GenerativeModel("gemini-2.5-flash-lite")


def check_length_consistency(actual: str, expected: str) -> float:
    actual_words = len(actual.split())
    expected_words = len(expected.split())

    if expected_words < 50:
        diff = abs(actual_words - expected_words)
        return 1.0 if diff <= 20 else max(0.0, 1.0 - (diff / 40))

    if expected_words == 0:
        return 0.0
    ratio = actual_words / expected_words

    if 0.5 <= ratio <= 2.0:
        return 1.0

    distance = min(abs(ratio - 0.5), abs(ratio - 2.0))
    return max(0.0, 1.0 - (distance / 2.0))


def check_format_adherence(actual: str, expected: str) -> float:
    actual = actual.strip()
    expected = expected.strip()

    if (expected.startswith("{") and expected.endswith("}")) or (expected.startswith("[") and expected.endswith("]")):
        try:
            clean_actual = actual
            if "```" in actual:
                clean_actual = actual.split("```")[-1]
                if clean_actual.startswith("json"):
                    clean_actual = clean_actual[4:]
                clean_actual = clean_actual.split("```")[0]
            json.loads(clean_actual.strip())
            return 1.0
        except Exception:  # noqa: BLE001
            return 0.0

    if re.search(r"(?m)^[\-\*]\s", expected):
        return 1.0 if re.search(r"(?m)^[\-\*]\s", actual) else 0.0

    return 1.0


def ai_judge_correctness(input_data: Any, output: str, expected: str) -> Dict[str, Any]:
    if output.startswith("ERROR:"):
        return {"score": 0.0, "reason": "Generation failed"}

    prompt = f"""
    Act as an impartial judge. Compare the Actual Response to the Expected Answer.

    INPUT DATA: {input_data}
    EXPECTED ANSWER (Ground Truth): {expected}
    ACTUAL RESPONSE: {output}

    EVALUATION CRITERIA:
    1. Accuracy: Does the actual response convey the same key facts/intent as the expected answer?
    2. Tone: Is the tone similar?

    OUTPUT JSON ONLY:
    {{
        "score": (0.0 to 1.0),
        "reason": "Concise explanation of the score"
    }}
    """
    try:
        resp = JUDGE_MODEL.generate_content(prompt)
        text = resp.text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {"score": 0.0, "reason": "Judge error during evaluation"}


def fill_prompt_template(prompt_template: str, input_dict: Dict[str, Any]) -> str:
    prompt_vars = re.findall(r"\{{1,2}\s*([a-zA-Z0-9_]+)\s*\}{1,2}", prompt_template)
    prompt_text = prompt_template

    if not prompt_vars:
        data_str = ""
        if isinstance(input_dict, dict) and len(input_dict) == 1:
            data_str = str(list(input_dict.values())[0])
        else:
            data_str = str(input_dict)
        return f"{prompt_text}\n\n---\nInput Data:\n{data_str}"

    if isinstance(input_dict, dict):
        for key, value in input_dict.items():
            prompt_text = prompt_text.replace(f"{{{{{key}}}}}", str(value)).replace(f"{{{key}}}", str(value))

        if len(input_dict) == 1 and len(set(prompt_vars)) == 1:
            input_key = list(input_dict.keys())[0]
            prompt_var = list(set(prompt_vars))[0]
            if input_key != prompt_var:
                prompt_text = prompt_text.replace(f"{{{{{prompt_var}}}}}", str(input_dict[input_key])).replace(
                    f"{{{prompt_var}}}", str(input_dict[input_key])
                )

    remaining_vars = re.findall(r"\{{1,2}\s*([a-zA-Z0-9_]+)\s*\}{1,2}", prompt_text)
    if remaining_vars and isinstance(input_dict, dict) and len(input_dict) == 1:
        only_value = next(iter(input_dict.values()))
        for var in set(remaining_vars):
            prompt_text = prompt_text.replace(f"{{{{{var}}}}}", str(only_value)).replace(f"{{{var}}}", str(only_value))

    return prompt_text


def evaluate_single_case(case: TestCase, prompt_template: str) -> Dict[str, Any]:
    try:
        input_dict = json.loads(case.input_data) if isinstance(case.input_data, str) else case.input_data
    except Exception:  # noqa: BLE001
        input_dict = {"input": case.input_data}

    prompt_text = fill_prompt_template(prompt_template, input_dict)

    try:
        response = GENERATION_MODEL.generate_content(prompt_text, generation_config={"temperature": 0.1})
        actual_output = response.text.strip()
    except Exception as exc:  # noqa: BLE001
        actual_output = f"ERROR: {exc}"

    if actual_output.startswith("ERROR:"):
        return {
            "final_score": 0.0,
            "metrics": {"logic": 0.0, "format": 0.0, "length": 0.0},
            "passed": False,
            "input": input_dict,
            "expected": case.expected_output,
            "actual": actual_output,
            "reason": "API/Model error",
        }

    judge = ai_judge_correctness(input_dict, actual_output, case.expected_output)
    logic_score = judge.get("score", 0)
    length_score = check_length_consistency(actual_output, case.expected_output)
    format_score = check_format_adherence(actual_output, case.expected_output)

    fail_reasons: List[str] = []
    if logic_score < 0.8:
        fail_reasons.append(f"Logic weak ({judge.get('reason', '')})")
    if format_score < 1.0:
        fail_reasons.append("Wrong format")
    if length_score < 0.8:
        act_len = len(actual_output.split())
        exp_len = len(case.expected_output.split())
        if act_len > exp_len * 2:
            fail_reasons.append(f"Too verbose ({act_len} vs {exp_len})")
        elif act_len < exp_len * 0.5:
            fail_reasons.append(f"Too brief ({act_len} vs {exp_len})")

    raw_score = (logic_score * 0.70) + (format_score * 0.15) + (length_score * 0.15)
    
    final_score = round(raw_score * 100, 1)    
    final_reason = "; ".join(fail_reasons) if fail_reasons else judge.get("reason", "Good match")

    return {
        "final_score": final_score,
        "metrics": {"logic": logic_score, "format": format_score, "length": length_score},
        "passed": final_score >= 85,
        "input": input_dict,
        "expected": case.expected_output,
        "actual": actual_output,
        "reason": final_reason,
    }


def run_evaluation(prompt_slug: str) -> Tuple[float, List[Dict[str, Any]]]:
    session = SessionLocal()
    try:
        prompt = session.query(Prompt).filter_by(slug=prompt_slug).first()
        if not prompt or not prompt.versions:
            return 0.0, []

        latest_version = max(prompt.versions, key=lambda version: version.version_number)
        test_cases = session.query(TestCase).filter_by(prompt_id=prompt.id).all()
        if not test_cases:
            return 0.0, []

        results: List[Dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(evaluate_single_case, case, latest_version.template_text): case for case in test_cases}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        avg_score = sum(result["final_score"] for result in results) / len(results) if results else 0.0
        pass_count = sum(1 for result in results if result["passed"])

        evaluation = EvaluationResult(
            version_id=latest_version.id,
            score=avg_score,
            pass_count=pass_count,
            fail_count=len(results) - pass_count,
            detailed_metrics={"failures": [result for result in results if not result["passed"]], "cases": results},
        )
        session.add(evaluation)
        session.commit()

        return avg_score, [result for result in results if not result["passed"]]
    finally:
        session.close()
