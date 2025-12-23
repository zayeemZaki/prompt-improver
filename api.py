import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from database import EvaluationResult, Prompt, PromptVersion, SessionLocal, TestCase
from generator import generate_synthetic_dataset
from optimizer import optimize_prompt

app = FastAPI()

import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class PromptResponse(BaseModel):
    slug: str
    version: int
    template_text: str
    rationale: Optional[str]


class OptimizeRequest(BaseModel):
    slug: str


class CreateProjectRequest(BaseModel):
    initial_prompt: str


class GenerateDataRequest(BaseModel):
    slug: str
    num_cases: int = 5


@app.get("/get_prompt")
def get_prompt(slug: str) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        prompt = session.query(Prompt).filter_by(slug=slug).first()
        if not prompt or not prompt.versions:
            raise HTTPException(status_code=404, detail="Prompt not found")

        latest_version = max(prompt.versions, key=lambda version: version.version_number)
        return {
            "slug": prompt.slug,
            "version": str(latest_version.version_number),
            "template_text": latest_version.template_text,
            "rationale": latest_version.rationale,
        }
    finally:
        session.close()


@app.post("/optimize")
def optimize(request: OptimizeRequest) -> Dict[str, Any]:
    logging.debug("Optimize endpoint hit")
    logging.info("Received request to optimize prompt")
    try:
        logging.info(f"Optimizing prompt for slug: {request.slug}")
        new_version = optimize_prompt(request.slug)
        logging.info("Optimization complete")
    except HTTPException as e:
        logging.error(f"HTTPException occurred: {e.detail}")
        raise
    except Exception as exc:  # noqa: BLE001
        logging.error(f"Unexpected error: {str(exc)}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if new_version:
        logging.info(f"New version created: v{new_version.version_number}")
        return {
            "status": "success",
            "message": f"Optimization complete. Created v{new_version.version_number}",
            "version": str(new_version.version_number),
        }

    logging.info("No improvement detected during optimization")
    return {"status": "no_change", "message": "No improvement detected."}


@app.post("/create_project")
def create_project(request: CreateProjectRequest) -> Dict[str, Any]:
    logging.info("Received request to create project")
    session = SessionLocal()
    try:
        logging.info("Generating slug for new project")
        generated_slug = f"proj_{str(uuid.uuid4())[:8]}"

        new_prompt = Prompt(slug=generated_slug)
        session.add(new_prompt)
        session.commit()
        session.refresh(new_prompt)
        logging.info("New prompt created and committed to the database")

        version_one = PromptVersion(
            prompt_id=new_prompt.id,
            version_number=1,
            template_text=request.initial_prompt,
            rationale="Initial draft created by user.",
            input_schema={},
        )
        session.add(version_one)
        session.commit()
        logging.info("Version one created and committed to the database")

        return {"status": "success", "slug": generated_slug, "version": str(1)}
    finally:
        session.close()
        logging.info("Database session closed")


@app.post("/generate_tests")
def generate_tests(request: GenerateDataRequest) -> Dict[str, object]:
    session = SessionLocal()
    try:
        prompt = session.query(Prompt).filter_by(slug=request.slug).first()
        if not prompt:
            raise HTTPException(status_code=404, detail="Project not found")

        latest_version = max(prompt.versions, key=lambda version: version.version_number)

        try:
            synthetic_data = generate_synthetic_dataset(latest_version.template_text, request.num_cases)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc

        new_cases: List[TestCase] = []
        for case in synthetic_data:
            input_data = case["input_data"]
            if isinstance(input_data, (dict, list)):
                input_data = json.dumps(input_data)

            expected_output = case["expected_output"]
            if isinstance(expected_output, (dict, list)):
                expected_output = json.dumps(expected_output)

            test_case = TestCase(
                prompt_id=prompt.id,
                input_data=input_data,
                expected_output=expected_output,
            )
            session.add(test_case)
            new_cases.append(case)

        session.commit()
        return {
            "status": "success",
            "message": f"Generated {len(new_cases)} test cases",
            "data": new_cases,
        }
    finally:
        session.close()


@app.get("/get_history")
def get_history(slug: str) -> List[Dict[str, object]]:
    session = SessionLocal()
    try:
        prompt = session.query(Prompt).filter_by(slug=slug).first()
        if not prompt:
            raise HTTPException(status_code=404, detail="Project not found")

        history_data: List[Dict[str, object]] = []
        for version in prompt.versions:
            result = (
                session.query(EvaluationResult)
                .filter_by(version_id=version.id)
                .order_by(EvaluationResult.run_at.desc())
                .first()
            )
            if result:
                history_data.append(
                    {
                        "version": version.version_number,
                        "score": result.score,
                        "pass_count": result.pass_count,
                        "fail_count": result.fail_count,
                        "rationale": version.rationale,
                        "template_text": version.template_text,
                        "metrics": result.detailed_metrics,
                    }
                )

        return sorted(history_data, key=lambda record: record["version"])
    finally:
        session.close()
