import json
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-2.5-pro")

def generate_synthetic_dataset(initial_prompt: str, num_cases: int = 5):
    
    meta_prompt = f"""
        You are an expert QA Engineer for LLM systems.
        Your goal is to generate a diverse, challenging test dataset to evaluate a specific prompt.
        
        THE PROMPT TO TEST:
        "{initial_prompt}"
        
        INSTRUCTIONS:
        1. Analyze what specific inputs this prompt expects (e.g., text, code, emails).
        2. Generate {num_cases} distinct test cases.
        3. Include "Edge Cases" (e.g., very short input, messy input, complex input).
        4. For each case, write the "input_data" and the "expected_output" (the ideal perfect response).
        
        OUTPUT FORMAT:
        Return ONLY a raw JSON list of objects. Do not use Markdown formatting.
        Example:
        [
            {{"input_data": "...", "expected_output": "..."}},
            {{"input_data": "...", "expected_output": "..."}}
        ]
    """

    try:
        response = model.generate_content(meta_prompt)

        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"Error generating data: {e}")
        return []

if __name__ == "__main__":
    test_prompt = "Summarize this news article into 5 bullet points."
    print("Generating data for:", test_prompt)
    results = generate_synthetic_dataset(test_prompt, 2)
    print(json.dumps(results, indent=2))