from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
from typing import Dict
import uvicorn
from dotenv import load_dotenv


app = FastAPI()

# Initialize the OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# In-memory storage for conversation threads
conversation_threads: Dict[str, str] = {}

class ConversationInput(BaseModel):
    assistant_id: str
    message: str
    conversation_id: str = None

class ConversationOutput(BaseModel):
    response: str
    conversation_id: str

@app.post("/chat", response_model=ConversationOutput)
async def chat_with_assistant(input: ConversationInput):
    try:
        # If conversation_id is provided and exists, use the existing thread
        # Otherwise, create a new thread
        if input.conversation_id and input.conversation_id in conversation_threads:
            thread_id = conversation_threads[input.conversation_id]
        else:
            thread = client.beta.threads.create()
            thread_id = thread.id
            # Generate a new conversation_id (you might want to use a more robust method)
            conversation_id = f"conv_{len(conversation_threads) + 1}"
            conversation_threads[conversation_id] = thread_id
        
        # Add the user's message to the thread
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=input.message
        )

        # Run the assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=input.assistant_id
        )

        # Wait for the run to complete
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

        # Retrieve the assistant's response
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        assistant_response = messages.data[0].content[0].text.value

        return ConversationOutput(
            response=assistant_response, 
            conversation_id=next(id for id, thread in conversation_threads.items() if thread == thread_id)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)