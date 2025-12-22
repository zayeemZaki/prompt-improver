import time
from database import SessionLocal, Prompt, EvaluationResult
import optimizer
import evaluator

PROMPT_SLUG = "news-summarizer"
TARGET_SCORE = 90.0
MAX_LOOPS = 3

def get_latest_score(slug):
    session = SessionLocal()

    prompt = session.query(Prompt).filter_by(slug=slug).first()
    if not prompt or not prompt.versions:
        session.close()
        return 0
    
    latest_version = max(prompt.versions, key=lambda v: v.version_number)
    
    result = session.query(EvaluationResult)\
        .filter_by(version_id=latest_version.id)\
        .order_by(EvaluationResult.run_at.desc())\
        .first()
        
    score = result.score if result else 0
    session.close()
    return score

def main():
    print(f"Starting CI/CD Loop for '{PROMPT_SLUG}'...")
    
    #  Baseline Check
    current_score = get_latest_score(PROMPT_SLUG)
    print(f"Baseline Score: {current_score}%")
    
    loop_count = 0
    
    while loop_count < MAX_LOOPS:
        loop_count += 1
        print(f"\n--- Iteration {loop_count} of {MAX_LOOPS} ---")
        
        optimizer.run_optimization(PROMPT_SLUG)
        
        time.sleep(1) 
        evaluator.run_evaluation(PROMPT_SLUG)
        
        new_score = get_latest_score(PROMPT_SLUG)
        
        if new_score >= TARGET_SCORE:
            print(f"SUCCESS! Target score reached: {new_score}%")
            break
            
        if new_score < current_score:
            print(f"Regression! Score dropped from {current_score}% to {new_score}%.")

            print("Stopping loop.")
            break
        
        if new_score == current_score:
             print(f"Stagnation. Score stuck at {new_score}%.")
             
        current_score = new_score

    print("\nOptimization Loop Finished.")
    
if __name__ == "__main__":
    main()