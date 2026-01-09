import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from database import EvaluationResult, Prompt, PromptVersion, SessionLocal
from evaluator import run_evaluation

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = genai.GenerativeModel("gemini-2.5-flash")


def get_variables(text: str) -> Set[str]:
    return set(re.findall(r"\{{1,2}\s*([a-zA-Z0-9_]+)\s*\}{1,2}", text))


def fetch_best_version(session: Session, prompt_id: int) -> Tuple[Optional[PromptVersion], Optional[EvaluationResult]]:
    best_pair = (
        session.query(PromptVersion, EvaluationResult)
        .join(EvaluationResult, PromptVersion.id == EvaluationResult.version_id)
        .filter(PromptVersion.prompt_id == prompt_id)
        .order_by(EvaluationResult.score.desc())
        .first()
    )
    return best_pair if best_pair else (None, None)


def ensure_required_variables(template: str) -> Set[str]:
    required_vars = get_variables(template)
    if not required_vars:
        required_vars = {"input"}
    return required_vars


def build_failure_summary(failures: List[Dict[str, Any]]) -> str:
    cleaned: List[Dict[str, Any]] = []
    for failure in failures[:3]:
        input_value = failure.get("input", failure.get("input_snippet", ""))
        if isinstance(input_value, dict):
            input_value = json.dumps(input_value)
        cleaned.append(
            {
                "input_snippet": str(input_value)[:150],
                "actual_output": str(failure.get("actual", ""))[:150],
                "error_analysis": failure.get("reason", failure.get("error_analysis", "")),
            }
        )
    return json.dumps(cleaned or [{"input_snippet": "(general)", "error_analysis": "Improve coverage and formatting."}], indent=2)


def restore_missing_variables(template: str, missing: Set[str]) -> str:
    if not missing:
        return template
    additions = "\n\nInputs:\n" + "\n".join(f"{{{{{var}}}}}" for var in sorted(missing))
    return f"{template.rstrip()}{additions}\n"


def optimize_prompt(slug: str) -> Optional[PromptVersion]:
    session = SessionLocal()
    baseline_failures: List[Dict[str, Any]] = []
    try:
        prompt = session.query(Prompt).filter_by(slug=slug).first()
        if not prompt:
            return None

        best_version, best_result = fetch_best_version(session, prompt.id)
        if not best_version:
            session.close()
            _, baseline_failures = run_evaluation(slug)
            session = SessionLocal()
            prompt = session.query(Prompt).filter_by(slug=slug).first()
            best_version, best_result = fetch_best_version(session, prompt.id)
        base_score = best_result.score if best_result else 0.0

        base_version = best_version or max(prompt.versions, key=lambda version: version.version_number)
        failures = (best_result.detailed_metrics.get("failures", []) if best_result else baseline_failures) or [
            {"input_snippet": "(general)", "error_analysis": "Cover edge cases and format strictly."}
        ]

        required_vars = ensure_required_variables(base_version.template_text)
        required_vars_str = ", ".join(f"{{{{{var}}}}}" for var in sorted(required_vars))

        failure_text = build_failure_summary(failures)
        meta_prompt = f"""
        You are an expert prompt engineer.

        Base prompt:
        "{base_version.template_text}"

        Required variables: {required_vars_str}

        Recent failures:
        {failure_text}

        Rewrite the base prompt to address the failures while preserving required variables.
        Return JSON only in the form:
        {{"improved_prompt": "...", "rationale": "..."}}
        """

        response = MODEL.generate_content(meta_prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        new_template = data.get("improved_prompt", "")
        rationale = data.get("rationale", "")

        missing_vars = required_vars - get_variables(new_template)
        if missing_vars:
            new_template = restore_missing_variables(new_template, missing_vars)
            rationale = rationale + " Missing variables were restored automatically." if rationale else "Missing variables were restored automatically."

        existing_versions = session.query(PromptVersion).filter_by(prompt_id=prompt.id).all()
        next_version_num = max(version.version_number for version in existing_versions) + 1

        new_version = PromptVersion(
            prompt_id=prompt.id,
            version_number=next_version_num,
            template_text=new_template,
            rationale=rationale,
            parent_version_id=base_version.id,
        )
        session.add(new_version)
        session.commit()
        session.refresh(new_version)
    except Exception:
        session.close()
        return None

    session.close()

    run_evaluation(slug)

    session = SessionLocal()
    try:
        new_eval = (
            session.query(EvaluationResult)
            .filter_by(version_id=new_version.id)
            .order_by(EvaluationResult.run_at.desc())
            .first()
        )
        # IMPORTANT: Do NOT delete failed attempts or regressions.
        # Every iteration (success or failure) must be saved to the database
        # so the frontend can plot the optimization history curve and show
        # the user that work is being done. Regression data is valuable for UX.
        # if base_score and new_eval and new_eval.score < base_score:
        #     session.delete(new_eval)
        #     session.delete(new_version)
        #     session.commit()
        #     return None
    finally:
        session.close()

    return new_version
