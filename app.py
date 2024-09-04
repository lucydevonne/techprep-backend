# app.py

from dotenv import load_dotenv
from flask import Flask, request, jsonify
import google.generativeai as genai
from flask_socketio import SocketIO, emit
import pyttsx3
import os
import re

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)
app = Flask(__name__)
socketio = SocketIO(app)

tts = pyttsx3.init('dummy') 

# Configure the Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-pro')

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

@socketio.on('audio_data')
def handle_audio_data(audio_data):
    print("Received audio data from client.")

    try:
        prompt = "Process this audio data and generate a response."
        response = model.generate_content(prompt, audio=audio_data)
        ai_response = response.text

        # Convert AI response text to speech using py3-tts
        tts.speak(ai_response)
        
        # Block while processing all the currently queued commands
        tts.runAndWait()

        # Send a success message back to the client
        emit('ai_response', {'data': ai_response})

    except Exception as e:
        print(f"Error processing audio data: {str(e)}")
        emit('ai_response', {'error': 'Failed to process audio data. Please try again.'})
        
        
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)