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

@app.route('/generate_question', methods=['POST'])
def generate_question():
    data = request.json
    topic = data.get('topic', 'JavaScript')
    difficulty = data.get('difficulty', 'Medium')
    
    prompt = f"""
    Generate a JavaScript coding interview question based on the following criteria:
    
    Topic: {topic}
    Difficulty: {difficulty}

    Please provide:
    1. A technical coding question that requires writing JavaScript code.
    2. The expected code solution.
    3. An explanation of the solution.

    Format your response as follows:
    Question: [Your generated question here]
    Solution: [The expected JavaScript code solution]
    Explanation: [Explanation of the solution]
    """

    try:
        response = model.generate_content(prompt)
        
        # Print the full response for debugging
        print(f"Full AI response:\n{response.text}")
        
        # Parse the response
        response_text = response.text
        question_start = response_text.find("Question:")
        solution_start = response_text.find("Solution:")
        explanation_start = response_text.find("Explanation:")
        
        if question_start == -1 or solution_start == -1 or explanation_start == -1:
            raise ValueError("Failed to find all required sections in the AI response")
        
        question = response_text[question_start:solution_start].replace("Question:", "").strip()
        solution = response_text[solution_start:explanation_start].replace("Solution:", "").strip()
        explanation = response_text[explanation_start:].replace("Explanation:", "").strip()
        
        return jsonify({
            "question": question,
            "solution": solution,
            "explanation": explanation
        })
    
    except Exception as e:
        print(f"Error generating question: {str(e)}")
        return jsonify({"error": "Failed to generate question. Please try again."}), 500

@app.route('/evaluate_answer', methods=['POST'])
def evaluate_answer():
    data = request.json
    question = data.get('question')
    user_answer = data.get('answer')
    expected_solution = data.get('solution')

    prompt = f"""
    Question: {question}
    
    Expected Solution:
    {expected_solution}
    
    User's Answer:
    {user_answer}
    
    Evaluate the user's JavaScript code answer against the expected solution. Provide feedback on:
    1. Correctness: Does it solve the problem?
    2. Efficiency: Is it an optimal solution?
    3. Code style: Is it well-written and following best practices?
    4. Suggestions for improvement.
    
    Format your response as a JSON string with the following keys:
    {{
        "correctness": "score from 0-10",
        "efficiency": "score from 0-10",
        "style": "score from 0-10",
        "feedback": "detailed feedback and suggestions"
    }}
    """

    try:
        response = model.generate_content(prompt)
        return response.text  # This should be a JSON string
    except Exception as e:
        print(f"Error evaluating answer: {str(e)}")
        return jsonify({"error": "Failed to evaluate answer. Please try again."}), 500

# WebSocket event handler for client connection
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('message', {'data': 'Welcome to the interview simulator!'})
    ask_question()

def ask_question():
    prompt = """
    Generate a JavaScript coding interview question based on the following criteria:
    
    Topic: JavaScript
    Difficulty: Medium

    Please provide:
    1. A technical coding question that requires writing JavaScript code.
    2. The expected code solution.
    3. An explanation of the solution.

    Format your response as follows:
    Question: [Your generated question here]
    Solution: [The expected JavaScript code solution]
    Explanation: [Explanation of the solution]
    """

    try:
        response = model.generate_content(prompt)
        question = response.text.split("Solution:")[0].replace("Question:", "").strip()
        emit('interview_question', {'data': question})
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
        prompt = "Transcribe the audio and then, as an AI interviewer for a JavaScript coding position, provide a relevant response or follow-up question based on the transcription."
        ai_response = generate_gemini_response(prompt, audio_data)

        if ai_response:
            print(f"Received response from Gemini API: {ai_response}")
            update_conversation_history(ai_response)
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