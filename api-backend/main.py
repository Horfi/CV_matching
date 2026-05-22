import os
import io
import google.generativeai as genai
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel, Field
from typing import List

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = FastAPI(title="CV Matcher API")

# JSON schema template for the CV data
class CVData(BaseModel):
    full_name: str
    email: str
    phone: str
    top_5_skills: List[str]
    summary_analysis: str = Field(description="Harsh critique of the CV, noting strengths and weak links.")
    total_years_experience: float = Field(description="Sum up all time periods of work experience (account for 'Present' as current date)")

OUTPUT_PATH = "/code/export_json/cv_data.json"
MODEL_NAME = "gemini-2.5-flash"

@app.post("/upload-cv")
async def upload_cv(file: UploadFile = File(...)):
    # Support PDF, PNG, JPG/JPEG
    allowed_types = ['application/pdf', 'image/png', 'image/jpeg', 'image/jpg']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only PDF, PNG, and JPEG files are supported.")
    
    try:
        # Read the raw bytes
        file_bytes = await file.read()

        # Prepare the Gemini Model
        model = genai.GenerativeModel(MODEL_NAME,
            generation_config={"response_mime_type": "application/json"}
        )
        
        prompt = f"""
        Extract resume data from the attached document/image and fill in a JSON structure that strictly matches this schema:
        {CVData.model_json_schema()}
        
        IMPORTANT:
        Double check the information you extract to ensure it's accurate. If you can't find a piece of information, leave it blank or as empty.
        Ensure your output is a valid JSON object matching the requested schema.
        """
        
        # Send the file directly to Gemini as inline data
        response = model.generate_content([
            prompt,
            {"mime_type": file.content_type, "data": file_bytes}
        ])
        
        # Validation - Check if the AI followed the rules
        validated_data = CVData.model_validate_json(response.text)
        
        # Save it via the export_json volume
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, 'w') as f:
            f.write(validated_data.model_dump_json(indent=4))
            
        print(f"Success! Data exported to: {OUTPUT_PATH}")
        
        return {
            "message": "CV processed successfully",
            "data": validated_data.model_dump()
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)