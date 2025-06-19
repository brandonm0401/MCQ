from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import mysql.connector
from starlette.status import HTTP_302_FOUND
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(SessionMiddleware, secret_key="your_secret_key")

DATABASE_CONFIG = {
    'user': 'admin',
    'password': 'admin',
    'host': 'localhost',
    'database': 'quiz',
}

def get_db_connection():
    conn = mysql.connector.connect(**DATABASE_CONFIG)
    return conn

class Answer(BaseModel):
    question_id: int
    selected_option: str

class Result(BaseModel):
    team_name: str
    participant1_name: str
    participant2_name: str
    participant1_mobile: str
    participant2_mobile: str
    answers: List[Answer]

@app.on_event("startup")
def startup_event():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        correct_answer CHAR(1) NOT NULL
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS results (
        id INT AUTO_INCREMENT PRIMARY KEY,
        team_name VARCHAR(255) NOT NULL,
        participant1_name VARCHAR(255) NOT NULL,
        participant2_name VARCHAR(255) NOT NULL,
        participant1_mobile VARCHAR(20) NOT NULL,
        participant2_mobile VARCHAR(20) NOT NULL,
        score INT NOT NULL,
        duration INT
    )
    ''')
    conn.commit()
    conn.close()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
def get_register(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request):
    team_name = request.session.get("team_name")
    if not team_name:
        return RedirectResponse(url="/register")
    return templates.TemplateResponse("welcome.html", {"request": request, "team_name": team_name})

@app.post("/start_quiz", response_class=HTMLResponse)
def start_quiz(request: Request, team_name: str = Form(), participant1_name: str = Form(), participant2_name: str = Form(), participant1_mobile: str = Form(), participant2_mobile: str = Form()):
    request.session["team_name"] = team_name
    request.session["participant1_name"] = participant1_name
    request.session["participant2_name"] = participant2_name
    request.session["participant1_mobile"] = participant1_mobile
    request.session["participant2_mobile"] = participant2_mobile
    request.session["current_question_id"] = 1
    request.session["answers"] = []
    request.session["start_time"] = datetime.now().isoformat()  # Capture the start time

    return RedirectResponse(url="/welcome", status_code=HTTP_302_FOUND)

@app.get("/quiz/{question_id}", response_class=HTMLResponse)
def get_question(request: Request, question_id: int):
    session = request.session

    if "current_question_id" not in session:
        return RedirectResponse(url="/results")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('SELECT * FROM questions WHERE id = %s', (question_id,))
        question = cursor.fetchone()
        
        cursor.execute('SELECT COUNT(*) FROM questions')
        total_questions = cursor.fetchone()['COUNT(*)']
    finally:
        cursor.close()
        conn.close()

    if not question or question_id > total_questions:
        return RedirectResponse(url="/results")

    is_last_question = (question_id == total_questions)
    is_first_question = (question_id == 1)

    selected_option = None
    for answer in session.get("answers", []):
        if answer["question_id"] == question_id:
            selected_option = answer["selected_option"]
            break

    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "question": question,
        "question_id": question_id,
        "team_name": session["team_name"],
        "participant1_name": session["participant1_name"],
        "participant2_name": session["participant2_name"],
        "participant1_mobile": session["participant1_mobile"],
        "participant2_mobile": session["participant2_mobile"],
        "is_last_question": is_last_question,
        "is_first_question": is_first_question,
        "selected_option": selected_option
    })

@app.post("/quiz/{question_id}", response_class=HTMLResponse)
def submit_answer(request: Request, question_id: int, selected_option: str = Form(default=None), prev: bool = Form(default=False)):
    session = request.session

    if "answers" not in session:
        session["answers"] = []

    # Update the answer if it exists, else append a new one
    answer_found = False
    for answer in session["answers"]:
        if answer["question_id"] == question_id:
            answer["selected_option"] = selected_option
            answer_found = True
            break

    if not answer_found:
        session["answers"].append({
            "question_id": question_id,
            "selected_option": selected_option
        })

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT COUNT(*) FROM questions')
        total_questions = cursor.fetchone()[0]

        if prev:
            previous_question_id = question_id - 1
            if previous_question_id < 1:
                previous_question_id = 1
            session["current_question_id"] = previous_question_id
            return RedirectResponse(url=f"/quiz/{previous_question_id}", status_code=HTTP_302_FOUND)
        else:
            next_question_id = question_id + 1
            if next_question_id > total_questions:
                return RedirectResponse(url="/results", status_code=HTTP_302_FOUND)
            else:
                session["current_question_id"] = next_question_id
                return RedirectResponse(url=f"/quiz/{next_question_id}", status_code=HTTP_302_FOUND)
    finally:
        cursor.close()
        conn.close()

@app.get("/results", response_class=HTMLResponse)
def show_results(request: Request):
    session = request.session
    if "answers" not in session:
        return RedirectResponse(url="/")

    conn = get_db_connection()
    cursor = conn.cursor()

    total_score = 0

    try:
        for answer in session["answers"]:
            question_id = answer["question_id"]
            selected_option = answer["selected_option"]
            cursor.execute('SELECT correct_answer FROM questions WHERE id = %s', (question_id,))
            correct_answer = cursor.fetchone()[0]
            if selected_option == correct_answer:
                total_score += 1

        session["results"] = {
            "team_name": session["team_name"],
            "total_score": total_score
        }

        end_time = datetime.now()
        start_time = datetime.fromisoformat(session["start_time"])
        duration = int((end_time - start_time).total_seconds())

        cursor.execute('''
            INSERT INTO results (team_name, participant1_name, participant2_name, participant1_mobile, participant2_mobile, score, duration)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (
            session["team_name"],
            session["participant1_name"],
            session["participant2_name"],
            session["participant1_mobile"],
            session["participant2_mobile"],
            total_score,
            duration
        ))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    response = templates.TemplateResponse("result.html", {
        "request": request,
        "team_name": session["results"]["team_name"],
        "total_score": session["results"]["total_score"]
    })
    session.clear()
    return response
