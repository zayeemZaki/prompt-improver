from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from database import SessionLocal, Prompt
from database import PromptVersion
from generator import generate_synthetic_dataset
from database import TestCase 
from optimizer import optimize_prompt
from database import EvaluationResult

app = FastAPI()

class PromptResponse(BaseModel):
    slug: str
    version: int
    template_text: str

class OptimizeRequest(BaseModel):
    slug: str

class CreateProjectRequest(BaseModel):
    slug: str
    initial_prompt: str

class GenerateDataRequest(BaseModel):
    slug: str
    num_cases: int = 5

@app.get("/get_prompt")
def get_prompt(slug: str):
    session = SessionLocal()
    prompt = session.query(Prompt).filter_by(slug=slug).first()
    
    if not prompt or not prompt.versions:
        session.close()
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    latest_version = max(prompt.versions, key=lambda v: v.version_number)
    
    result = {
        "slug": prompt.slug,
        "version": latest_version.version_number,
        "template_text": latest_version.template_text,
        "rationale": latest_version.rationale 
    }
    
    session.close()
    return result

@app.post("/optimize")
def optimize(request: OptimizeRequest):
    try:
        new_version = optimize_prompt(request.slug)
        
        if new_version:
            return {
                "status": "success", 
                "message": f"Optimization complete. Created v{new_version.version_number}",
                "version": new_version.version_number
            }
        else:
             return {
                "status": "no_change", 
                "message": "Optimization ran but no improvement was needed."
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.post("/create_project")
def create_project(request: CreateProjectRequest):
    session = SessionLocal()
    
    if session.query(Prompt).filter_by(slug=request.slug).first():
        session.close()
        raise HTTPException(status_code=400, detail="Project already exists")
    
    new_prompt = Prompt(slug=request.slug)
    session.add(new_prompt)
    session.commit()
    session.refresh(new_prompt)
    
    v1 = PromptVersion(
        prompt_id=new_prompt.id,
        version_number=1,
        template_text=request.initial_prompt,
        rationale="Initial Draft created by User via API.",
        input_schema={}
    )
    session.add(v1)
    session.commit()
    
    session.close()
    return {"status": "success", "slug": request.slug, "version": 1}

@app.post("/generate_tests")
def generate_tests(request: GenerateDataRequest):
    session = SessionLocal()
    
    prompt = session.query(Prompt).filter_by(slug=request.slug).first()
    if not prompt:
        session.close()
        raise HTTPException(status_code=404, detail="Project not found")
        
    latest_version = max(prompt.versions, key=lambda v: v.version_number)
    
    try:
        synthetic_data = generate_synthetic_dataset(latest_version.template_text, request.num_cases)
    except Exception as e:
        session.close()
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    new_cases = []
    for case in synthetic_data:
        import json
        
        input_d = case['input_data']
        if isinstance(input_d, (dict, list)):
            input_d = json.dumps(input_d)
            
        expected = case['expected_output']
        if isinstance(expected, (dict, list)):
            expected = json.dumps(expected)
            
        new_case = TestCase(
            prompt_id=prompt.id,
            input_data=input_d,  # Use the string version here
            expected_output=expected
        )
        session.add(new_case)
        new_cases.append(case)
    
    session.commit()
    session.close()
    
    return {
        "status": "success", 
        "message": f"Generated {len(new_cases)} test cases", 
        "data": new_cases
    }

@app.get("/get_history")
def get_history(slug: str):
    session = SessionLocal()
    prompt = session.query(Prompt).filter_by(slug=slug).first()
    
    if not prompt:
        session.close()
        raise HTTPException(status_code=404, detail="Project not found")
        
    history_data = []
    
    for version in prompt.versions:
        result = session.query(EvaluationResult)\
            .filter_by(version_id=version.id)\
            .order_by(EvaluationResult.run_at.desc())\
            .first()
            
        if result:
            history_data.append({
                "version": version.version_number,
                "score": result.score,
                "pass_count": result.pass_count,
                "fail_count": result.fail_count,
                "rationale": version.rationale
            })
            
    session.close()
    return sorted(history_data, key=lambda x: x['version'])