# app.py

from flask import Flask, request, jsonify
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure the Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-pro')

@app.route('/generate_question', methods=['POST'])
def generate_question():
    data = request.json
    topic = data.get('topic')
    difficulty = data.get('difficulty')

    prompt = f"Generate a {difficulty} technical interview question about {topic}."
    response = model.generate_content(prompt)

    return jsonify({
        "question": response.text
    })

@app.route('/evaluate_answer', methods=['POST'])
def evaluate_answer():
    data = request.json
    question = data.get('question')
    user_answer = data.get('answer')

    prompt = f"Question: {question}\nUser's Answer: {user_answer}\nEvaluate the answer and provide feedback."
    response = model.generate_content(prompt)

    return jsonify({
        "feedback": response.text
    })

if __name__ == '__main__':
    app.run(debug=True)