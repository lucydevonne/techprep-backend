# app.py

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import pyttsx3
import os
import re
import tempfile
import traceback
import time
from functools import wraps
# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)
app = Flask(__name__)
# Configure CORS
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})

# Initialize SocketIO with CORS settings
socketio = SocketIO(app, cors_allowed_origins="http://localhost:3000")

tts = pyttsx3.init('dummy') 

# Configure the Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

# WebSocket event handler for client connection
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('message', {'data': 'Welcome to the interview simulator!'})
    ask_question()

current_question = ""
interviewer_notes = ""

def ask_question():
    global current_question, interviewer_notes
    prompt = """
    As an experienced JavaScript interviewer, generate a coding interview question for a mid-level JavaScript developer position. Follow these guidelines:
    
    1. Topic: Choose a relevant JavaScript concept (e.g., closures, promises, async/await, prototypes, etc.)
    2. Difficulty: Medium level
    3. Question Type: Ask the candidate to write a function or explain a concept with code

    Format your response as follows:
    Question: [Your generated interview question here]
    Interviewer Notes: [Brief notes on what to look for in the answer, not to be shared with the candidate]

    Remember to be concise and clear in your question, as if you're speaking directly to the candidate.
    """

    try:
        response = model.generate_content(prompt)
        question_parts = response.text.split("Interviewer Notes:")
        current_question = question_parts[0].replace("Question:", "").strip()
        interviewer_notes = question_parts[1].strip() if len(question_parts) > 1 else ""
        
        update_conversation_history(f"Interviewer: {current_question}")
        emit('interview_question', {'data': current_question})
    except Exception as e:
        print(f"Error generating question: {str(e)}")
        emit('interview_question', {'error': 'Failed to generate question. Please try again.'})
@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# Rate limiting
RATE_LIMIT = 1  # 1 request per second
last_request_time = 0
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        global last_request_time
        current_time = time.time()
        if current_time - last_request_time < RATE_LIMIT:
            time.sleep(RATE_LIMIT - (current_time - last_request_time))
        last_request_time = time.time()
        return f(*args, **kwargs)
    return wrapper

# Conversation context
conversation_history = []
MAX_HISTORY_LENGTH = 5  # Adjust as needed

def update_conversation_history(message):
    global conversation_history
    conversation_history.append(message)
    if len(conversation_history) > MAX_HISTORY_LENGTH:
        conversation_history.pop(0)

def get_conversation_context():
    return "\n".join(conversation_history)

@rate_limited
def generate_gemini_response(prompt, audio_data=None):
    for attempt in range(MAX_RETRIES):
        try:
            context = get_conversation_context()
            full_prompt = f"{context}\n\n{prompt}"
            print(f"Sending prompt to Gemini API:\n{full_prompt}")
            if audio_data:
                response = model.generate_content([
                    full_prompt,
                    {
                        "mime_type": "audio/mp3",
                        "data": audio_data
                    }
                ])
            else:
                response = model.generate_content(full_prompt)
            
            return response.text
        except Exception as e:
            print(f"Error generating response (attempt {attempt + 1}/{MAX_RETRIES}): {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    
    print("Max retries reached. Failing.")
    return None

@socketio.on('audio_data')
def handle_audio_data(audio_data):
    global current_question
    print("Received audio data from client.")

    try:
        # Check audio data size
        audio_size = len(audio_data)
        print(f"Audio data size: {audio_size} bytes")
        if audio_size > 10 * 1024 * 1024:  # 10 MB limit
            raise ValueError("Audio file too large. Maximum size is 10 MB.")

        # Save audio data to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
            temp_audio.write(audio_data)
            temp_audio_path = temp_audio.name

        print(f"Audio saved to temporary file: {temp_audio_path}")

        # Process audio with Gemini
        with open(temp_audio_path, 'rb') as f:
            audio_data = f.read()

        print("Sending audio data to Gemini API")
        prompt = f"""
        As an AI JavaScript interviewer, you're conducting a coding interview. The current question is:

        {current_question}

        Interviewer Notes: {interviewer_notes}

        The candidate has just provided an audio response. Your task is to:
        1. Briefly summarize the candidate's response (1-2 sentences).
        2. Provide a follow-up question or request for clarification based on their answer.
        3. If needed, guide the candidate towards a better solution without giving it away completely.

        Maintain a professional and encouraging tone throughout your response. Your goal is to assess the candidate's knowledge and problem-solving skills, not to trick them.

        Format your response as:
        Summary: [Brief summary of candidate's response]
        Follow-up: [Your follow-up question or request for clarification]
        """
        ai_response = generate_gemini_response(prompt, audio_data)

        if ai_response:
            print(f"Received response from Gemini API: {ai_response}")
            update_conversation_history(f"Candidate: [Audio Response]\nInterviewer: {ai_response}")
            emit('ai_response', {'text': ai_response})
        else:
            raise Exception("Failed to generate response from Gemini API")

    except ValueError as ve:
        print(f"Value Error: {str(ve)}")
        emit('ai_response', {'error': str(ve)})
    except Exception as e:
        print(f"Error processing audio data: {str(e)}")
        print(traceback.format_exc())
        fallback_response = generate_gemini_response("As an AI interviewer for a JavaScript coding position, provide a general follow-up question or comment.")
        if fallback_response:
            emit('ai_response', {'text': f"I couldn't process the audio, but let's continue. {fallback_response}"})
        else:
            emit('ai_response', {'error': 'Failed to process audio and generate a fallback response. Please try again.'})
    finally:
        # Clean up the temporary audio file
        if 'temp_audio_path' in locals() and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
            print(f"Removed temporary file: {temp_audio_path}")

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_file(filename, mimetype="audio/mp3")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)