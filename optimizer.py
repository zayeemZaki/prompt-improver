import os
import json
import google.generativeai as genai
from database import SessionLocal, Prompt, PromptVersion
from evaluator import run_evaluation
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-pro') 

def optimize_prompt(slug: str):
    print(f"Starting Optimization Loop for: {slug}")
    session = SessionLocal()
    
    # Evaluate CURRENT Version
    print("   Running pre-optimization evaluation...")
    score, failures = run_evaluation(slug)

    # Get prompt data
    prompt = session.query(Prompt).filter_by(slug=slug).first()
    latest_version = max(prompt.versions, key=lambda v: v.version_number)

    if not failures:
        print("    Score is perfect! Inventing a nitpick...")
        failures = [{"input": "example", "actual": "output", "judge_reasoning": "Make it more concise."}]

    failure_text = json.dumps(failures[:3], indent=2)
    
    # UPDATED META-PROMPT WITH STRICT SYNTAX RULES
    meta_prompt = f"""
        You are an expert Prompt Engineer.
        
        YOUR GOAL: Optimize the prompt to fix the failures listed below.
        
        CURRENT PROMPT:
        "{latest_version.template_text}"
        
        FAILURES:
        {failure_text}
        
        CRITICAL INSTRUCTIONS:
        1. Analyze why the prompt failed.
        2. Rewrite the prompt to be more robust.
        3. **PRESERVE VARIABLES:** You MUST keep the double-curly-brace syntax for variables (e.g. `{{{{article}}}}`, `{{{{code}}}}`). 
        - Do NOT change them to single braces like `{{code}}`.
        - Do NOT remove them.
        - The system relies on exact matching for `{{{{variable_name}}}}`.
        4. Return ONLY valid JSON.
        
        OUTPUT FORMAT:
        {{
            "improved_prompt": "...",
            "rationale": "..."
        }}
    """
    
    try:
        response = model.generate_content(meta_prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        data = json.loads(text)
        
        new_template = data["improved_prompt"]
        rationale = data["rationale"]
        
    except Exception as e:
        print(f"Error: {e}")
        session.close()
        return

    new_version = PromptVersion(
        prompt_id=prompt.id,
        version_number=latest_version.version_number + 1,
        template_text=new_template,
        rationale=rationale,
        parent_version_id=latest_version.id
    )
    
    session.add(new_version)
    session.commit()
    print(f"Created Version {new_version.version_number}")
    session.close()
    
    # Run Eval for New Version
    print(f"   Evaluating v{new_version.version_number}...")
    run_evaluation(slug)

    return new_version