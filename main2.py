import streamlit as st
import openai
from openai import OpenAI
import time
from dotenv import load_dotenv
import os
import json

load_dotenv()

# Streamlit app setup
st.title("Sabiro - Asistente Virtual")

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Create or load assistant
assistant_id = "asst_BblktfdFkyXnnNhuobNPhCMC"
print(f"Assistant ID: {assistant_id}")
if not assistant_id:
    assistant = client.beta.assistants.create(
        name="Streamlit Assistant",
        instructions="You are a helpful assistant in a Streamlit app.",
        model="gpt-4-1106-preview",
        tools=[{"type": "retrieval"}]  # Enable retrieval
    )
    st.secrets["ASSISTANT_ID"] = assistant.id
else:
    assistant = client.beta.assistants.retrieve(assistant_id)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Function to display sources with snippets
def display_sources_with_snippets(sources):
    st.info("Sources:")
    for i, source in enumerate(sources, 1):
        st.write(f"{i}. {source['file']}")
        st.write(f"   Score: {source['score']:.2f}")
        if 'snippet' in source:
            with st.expander("View snippet"):
                st.text(source['snippet'])
    st.write(f"Total sources displayed: {len(sources)}")

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "sources" in message and message["sources"]:
            display_sources_with_snippets(message["sources"])

# Chat input
if prompt := st.chat_input("What is your question?"):
    # Append the instruction to the user's prompt
    full_prompt = f"{prompt}\n\nRecuerda que en el caso de que hagas retrieval y estes usando los archivos del estatuto tributario, SIEMPRE debes darme la fuente, eso es el artículo y lo que dice ese artículo de donde sacaste la información"
    
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Create a thread and add user message with the appended instruction
    thread = client.beta.threads.create()
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=full_prompt
    )

    # Run the assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id,
    )

    # Wait for the assistant to complete
    while run.status not in ["completed", "failed"]:
        time.sleep(1)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        print(f"Run status: {run.status}")

    if run.status == "failed":
        st.error(f"Run failed: {run.last_error}")
        st.stop()

    # Retrieve the assistant's response
    messages = client.beta.threads.messages.list(thread_id=thread.id)
    assistant_message = messages.data[0].content[0].text.value

    # Retrieve source information
    sources = []
    run_steps = client.beta.threads.runs.steps.list(thread_id=thread.id, run_id=run.id)
    
    for step in run_steps.data:
        step_dict = step.dict()
        if step_dict.get("type") == "tool_calls":
            tool_calls = step_dict.get("step_details", {}).get("tool_calls", [])
            for tool_call in tool_calls:
                if isinstance(tool_call, dict) and tool_call.get("type") == "file_search":
                    file_search = tool_call.get("file_search", {})
                    file_search_results = file_search.get("results", [])
                    for result in file_search_results:
                        source = {
                            "file": result.get("file_name", "Unknown file"),
                            "score": result.get("score", 0)
                        }
                        if "file_citation" in result:
                            source["snippet"] = result["file_citation"].get("quote", "")
                        elif "file_path" in result:
                            source["snippet"] = result.get("text", "")
                        sources.append(source)

    # Add message and sources to session state
    st.session_state.messages.append({
        "role": "assistant", 
        "content": assistant_message,
        "sources": sources
    })
    
    # Display the assistant's response and sources
    with st.chat_message("assistant"):
        st.markdown(assistant_message)
        if sources:
            display_sources_with_snippets(sources)
        else:
            st.info("No specific sources were cited for this response.")

    # Debugging: Display raw run steps
    with st.expander("Debug: Raw Run Steps"):
        st.json([step.dict() for step in run_steps.data])

    # Debugging: Display total number of sources
    st.write(f"Total sources found: {len(sources)}")