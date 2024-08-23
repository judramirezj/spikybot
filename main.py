from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
import uvicorn
import asyncio
import nest_asyncio
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
assistant_id = os.getenv("ASSISTANT_ID")

class Message(BaseModel):
    thread_id: str = None
    content: str

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1B_tx8gGzLrnCuTsNpFfS3kG-QmsahuLs71Jw8U2L8VQ"

def get_google_sheets_service():
    credentials = None
    if os.path.exists("token.json"):
        credentials = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            credentials = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(credentials.to_json())

    return build("sheets", "v4", credentials=credentials)

# Define the function for extracting order data
extract_order_function = {
  "name": "extract_order_data",
  "description": "Extract order data from the conversation",
  "parameters": {
    "type": "object",
    "properties": {
      "nombre": {
        "type": "string",
        "description": "Customer's name"
      },
      "orden": {
        "type": "string",
        "description": "Details of the order"
      },
      "entrega": {
        "type": "string",
        "description": "Delivery method: 'Domicilio' or 'Para Recoger'"
      },
      "dirección": {
        "type": "string",
        "description": "Customer's address for delivery. Use 'EN EL RESTAURANTE' if entrega is 'Para Recoger'"
      },
      "metodo_de_pago": {
        "type": "string",
        "description": "Payment method"
      }
    },
    "required": ["nombre", "orden", "entrega", "dirección", "metodo_de_pago"]
  }
}

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/chat")
async def chat(message: Message):
    try:
        if message.thread_id:
            thread = client.beta.threads.retrieve(message.thread_id)
        else:
            thread = client.beta.threads.create()

        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=message.content
        )
        
        # Force function call
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id,
            tools=[{"type": "function", "function": extract_order_function}],
            instructions="Always call the extract_order_data function with the information provided, even if incomplete."
        )
        
        while run.status not in ["completed", "failed", "requires_action"]:
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            logger.info(f"Run status: {run.status}")
        
        if run.status == "failed":
            logger.error(f"Run failed: {run.last_error}")
            raise Exception(f"Run failed: {run.last_error}")
        
        if run.status == "requires_action":
            logger.info("Function call required")
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            tool_outputs = []
            for tool_call in tool_calls:
                if tool_call.function.name == "extract_order_data":
                    logger.info(f"Extracting order data: {tool_call.function.arguments}")
                    order_data = json.loads(tool_call.function.arguments)
                    success = save_to_sheets(order_data)
                    output = json.dumps({"success": success})
                    tool_outputs.append({"tool_call_id": tool_call.id, "output": output})
            
            run = client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )
            
            # Wait for the run to complete after submitting tool outputs
            while run.status not in ["completed", "failed"]:
                run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                logger.info(f"Run status after tool output submission: {run.status}")
        
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        assistant_message = next((msg for msg in messages.data if msg.role == "assistant"), None)
        
        if assistant_message is None:
            logger.warning("No assistant response found.")
            return {
                "thread_id": thread.id,
                "response": "No assistant response found."
            }
        
        logger.info(f"Assistant response: {assistant_message.content[0].text.value}")
        return {
            "thread_id": thread.id,
            "response": assistant_message.content[0].text.value
        }
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def save_to_sheets(order_data):
    try:
        logger.info(f"Attempting to save order data: {order_data}")
        service = get_google_sheets_service()
        sheets = service.spreadsheets()
        
        # Find the next empty row
        result = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range="Hoja 1!A:A").execute()
        next_row = len(result.get('values', [])) + 1
        logger.info(f"Next empty row: {next_row}")
        
        values = [
            [order_data.get("nombre", ""), order_data.get("orden", ""), order_data.get("entrega", ""), order_data.get('dirección'), order_data.get("metodo_de_pago", "")]
        ]
        
        logger.info(f"Appending values to row {next_row}: {values}")
        response = sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"Hoja 1!A{next_row}",
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        
        logger.info(f"Append response: {response}")
        return True
    except HttpError as error:
        logger.error(f"An error occurred while saving to Google Sheets: {error}", exc_info=True)
        return False

def start_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    return server.serve()

if __name__ == "__main__":
    asyncio.run(start_server())
else:
    # This allows the app to be imported without immediately starting the server
    nest_asyncio.apply()