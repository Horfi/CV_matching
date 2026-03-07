import ollama
import json
import os
from pydantic import BaseModel, Field
from typing import List 

#json scchema template for the CV data
class CVData(BaseModel):
    full_name: str
    email: str
    phone: str
    top_5_skills: List[str]
    summary_analysis: str = Field(description="Harsh critique of the CV, noting strengths and weak links.")
    total_years_experience: float = Field(description="Sum up all time periods of work experience (account for 'Present' as current date)")


# Connect to the AI container
client = ollama.Client(host='http://ollama:11434')

# Configuration
IMAGE_PATH = "/code/images/1.png"  # Inside the container, it's at /code/...
OUTPUT_PATH = "/code/export_json/cv_data.json"
MODEL_NAME = "llama3.2-vision"

def extract_cv_data():
    print(f" Reading CV from: {IMAGE_PATH}")
    
    # The instructions for the AI
    prompt = """
        Extract resume data and fill in the following JSON structure example: 
        {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
            "phone": "+1-555-123-4567",
            "top_5_skills": ["Python", "Data Analysis", "Machine Learning", "SQL", "Project Management"],
            "summary_analysis": "Harsh critique of the CV, noting strengths and weak links.",
            "total_years_experience": 5.0
        }
        IMPORTANT:  
        Double check the information you extract to ensure it's accurate. If you can't find a piece of information, leave it blank or as an empty.
        """

    try:
        # Send the image to the Vision model
        response = client.chat(
            model=MODEL_NAME,
            format=CVData.model_json_schema(),  # This tells the model to respond in the structure of CVData
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [IMAGE_PATH]
            }]
        )

        # 3. Validation - Check if the AI followed the rules
        raw_content = response['message']['content']
        validated_data = CVData.model_validate_json(raw_content)
        
        # Save it to your D: drive (via the export_json volume)
        with open(OUTPUT_PATH, 'w') as f:
            f.write(validated_data.model_dump_json(indent=4))
            
        print(f"Success! Data exported to: {OUTPUT_PATH}")
        print("-" * 30)
        print(validated_data.model_dump_json(indent=4))

    except Exception as e:
        print(f" Error: {e}")

if __name__ == "__main__":
    if os.path.exists(IMAGE_PATH):
        extract_cv_data()
    else:
        print(f"Image not found at {IMAGE_PATH}. Check your filename!")