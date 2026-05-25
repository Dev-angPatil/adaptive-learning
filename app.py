"""
Main Flask application for the Adaptive Python Learning Platform.
Integrates database models, quiz engine, adaptive path selection, and analytics visualization.
"""

import os
import re
import sys
import time
from typing import Dict, Any

from flask import Flask, render_template, redirect, request, session, url_for, flash
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from dotenv import load_dotenv

# Ensure the project directory is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import Base, Topic, Video, QuizQuestion, QuizAttempt, LearningSession
from engine.quiz import get_questions_for_topic, grade_quiz_submission
from engine.progress import calculate_topic_mastery, calculate_score_trend, generate_progress_chart

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-123456789")

# Setup scoped database session
db_url = os.getenv("DATABASE_URL", "sqlite:///adaptive_learning.db")
engine = create_engine(db_url, connect_args={"check_same_thread": False})

# Ensure tables exist
Base.metadata.create_all(engine)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


@app.teardown_appcontext
def shutdown_session(exception=None):
    """Closes database session on request end."""
    db_session.remove()


def extract_youtube_video_id(url: str) -> str:
    """
    Extract 11-character video ID from any standard YouTube URL.
    """
    pattern = re.compile(
        r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    )
    match = pattern.search(url)
    return match.group(1) if match else ""


def get_user_stats():
    """
    Compute total XP and current level based on completed actions:
    - 100 XP per watched video
    - 50 XP per correct quiz question answered
    """
    watched_count = db_session.query(LearningSession).filter_by(watched=True).count()
    correct_count = (
        db_session.query(QuizAttempt.question_id)
        .filter_by(is_correct=True)
        .distinct()
        .count()
    )
    
    xp = (watched_count * 100) + (correct_count * 50)
    level = int(xp / 1000) + 1
    return xp, level


def get_current_focus():
    """
    Determine the next video lesson to study.
    Finds the first video (by order_in_topic and topic difficulty) that is unwatched.
    """
    # Get topics sorted by ID
    topics = db_session.query(Topic).order_by(Topic.id).all()
    for topic in topics:
        # Get videos sorted by order
        videos = db_session.query(Video).filter_by(topic_id=topic.id).order_by(Video.order_in_topic).all()
        for video in videos:
            session_record = db_session.query(LearningSession).filter_by(video_id=video.id).first()
            if not session_record or not session_record.watched:
                return {
                    "video_id": video.id,
                    "topic_name": topic.name,
                    "subtopic": video.subtopic
                }
    return {"video_id": None, "topic_name": None, "subtopic": None}


@app.route("/")
def dashboard():
    """
    Render the main Skill Tree / Dashboard view.
    """
    # 1. Fetch topics
    topics = db_session.query(Topic).order_by(Topic.id).all()
    
    # 2. Get user analytics
    xp, level = get_user_stats()
    
    # 3. Calculate status for each topic node
    nodes = []
    completed_topics_count = 0
    
    for idx, topic in enumerate(topics):
        # Calculate video progress for status classification
        videos = db_session.query(Video).filter_by(topic_id=topic.id).all()
        total_videos = len(videos)
        
        watched_count = (
            db_session.query(LearningSession)
            .filter(LearningSession.topic_id == topic.id, LearningSession.watched == True)
            .count()
        )
        
        # Check if previous topic is mastered to see if this is locked
        prereq_met = True
        if idx > 0:
            prev_topic = topics[idx - 1]
            if prev_topic.mastery_percentage < 40.0:
                prereq_met = False

        status = "Locked"
        if topic.mastery_percentage == 100.0:
            status = "Mastered"
            completed_topics_count += 1
        elif not prereq_met:
            status = "Locked"
        elif topic.mastery_percentage > 0.0 or watched_count > 0:
            status = "In Progress"
        else:
            status = "Unlocked"

        # Populate videos list for course rendering
        videos_list = []
        for v in videos:
            session_record = db_session.query(LearningSession).filter_by(video_id=v.id).first()
            watched = session_record.watched if session_record else False
            videos_list.append({
                "id": v.id,
                "subtopic": v.subtopic,
                "duration_minutes": v.duration_minutes,
                "watched": watched
            })

        nodes.append({
            "id": topic.id,
            "name": topic.name,
            "description": topic.description or f"Learn core concepts about {topic.name}.",
            "difficulty": topic.difficulty,
            "mastery_percentage": int(topic.mastery_percentage),
            "status": status,
            "videos": videos_list
        })

    # 4. Get active lesson focus
    current_focus = get_current_focus()

    return render_template(
        "dashboard.html",
        nodes=nodes,
        xp=xp,
        level=level,
        current_focus=current_focus,
        active_tab="dashboard"
    )


@app.route("/lesson/<int:video_id>")
def lesson(video_id):
    """
    Render a single video lesson page.
    """
    video = db_session.get(Video, video_id)
    if not video:
        flash("Lesson not found.", "error")
        return redirect(url_for("dashboard"))

    # Extract YouTube video ID
    yt_video_id = extract_youtube_video_id(video.youtube_url)
    
    current_focus = get_current_focus()

    return render_template(
        "lesson.html",
        video=video,
        yt_video_id=yt_video_id,
        current_focus=current_focus,
        active_tab="lesson"
    )


@app.route("/lesson/<int:video_id>/complete", methods=["POST"])
def lesson_complete(video_id):
    """
    Mark a lesson video as watched and automatically direct user to the topic quiz.
    """
    video = db_session.get(Video, video_id)
    if not video:
        return redirect(url_for("dashboard"))

    # Upsert LearningSession watched state
    session_record = db_session.query(LearningSession).filter_by(video_id=video_id).first()
    if not session_record:
        session_record = LearningSession(
            topic_id=video.topic_id,
            video_id=video_id,
            watched=True
        )
        db_session.add(session_record)
    else:
        session_record.watched = True
    
    db_session.commit()

    # Clear current quiz state
    session.pop("quiz_questions", None)
    session.pop("quiz_answers", None)
    session.pop("quiz_index", None)

    # Redirect to video-specific quiz
    return redirect(url_for("quiz_video", video_id=video_id))

@app.route("/quiz/video/<int:video_id>", methods=["GET", "POST"])
def quiz_video(video_id):
    """
    Video-specific quiz: 3 questions unique to this video.
    """
    video = db_session.get(Video, video_id)
    if not video:
        return redirect(url_for("dashboard"))

    topic = db_session.get(Topic, video.topic_id)
    quiz_session_key = f"quiz_video_{video_id}"

    # Initialize quiz session for this specific video
    if quiz_session_key not in session:
        questions = (
            db_session.query(QuizQuestion)
            .filter_by(video_id=video_id)
            .order_by(QuizQuestion.id)
            .all()
        )
        # Fallback to topic questions if somehow no video-specific ones exist
        if not questions:
            questions = (
                db_session.query(QuizQuestion)
                .filter_by(topic_id=video.topic_id)
                .limit(3)
                .all()
            )
        if not questions:
            flash("No quiz questions available for this video yet.", "warning")
            return redirect(url_for("dashboard"))

        session[quiz_session_key] = [q.id for q in questions]
        session[f"{quiz_session_key}_answers"] = {}
        session[f"{quiz_session_key}_index"] = 0

    question_ids = session[quiz_session_key]
    q_index = int(request.args.get("q", session.get(f"{quiz_session_key}_index", 0)))

    if q_index >= len(question_ids):
        return redirect(url_for("dashboard"))

    session[f"{quiz_session_key}_index"] = q_index

    if request.method == "POST":
        selected = request.form.get("selected_option")
        if not selected:
            flash("Please select an option before proceeding.", "warning")
            return redirect(url_for("quiz_video", video_id=video_id, q=q_index))

        q_id_str = str(question_ids[q_index])
        answers = session.get(f"{quiz_session_key}_answers", {})
        answers[q_id_str] = selected
        session[f"{quiz_session_key}_answers"] = answers

        if q_index + 1 >= len(question_ids):
            # Grade the video quiz
            submission_dict = {int(k): v for k, v in answers.items()}
            results, recommendation = grade_quiz_submission(db_session, video.topic_id, submission_dict)

            session["last_results"] = results
            session["last_recommendation"] = recommendation

            # Clean up video quiz session
            session.pop(quiz_session_key, None)
            session.pop(f"{quiz_session_key}_answers", None)
            session.pop(f"{quiz_session_key}_index", None)

            return redirect(url_for("results"))
        else:
            return redirect(url_for("quiz_video", video_id=video_id, q=q_index + 1))

    # GET: render the quiz question
    question = db_session.get(QuizQuestion, question_ids[q_index])
    progress_percent = int((q_index / len(question_ids)) * 100)
    current_focus = get_current_focus()

    return render_template(
        "quiz.html",
        topic=topic,
        question=question,
        q_index=q_index,
        q_count=len(question_ids),
        progress_percent=progress_percent,
        is_last=(q_index + 1 == len(question_ids)),
        current_focus=current_focus,
        video=video,
        active_tab="lesson"
    )



@app.route("/quiz/<int:topic_id>", methods=["GET", "POST"])
def quiz(topic_id):
    """
    Multi-step quiz runner. Renders and submits answers one question at a time.
    """
    topic = db_session.get(Topic, topic_id)
    if not topic:
        return redirect(url_for("dashboard"))

    # Initialize quiz in session if not present
    if "quiz_questions" not in session or session.get("quiz_topic_id") != topic_id:
        # Determine current recommended difficulty (default 1)
        difficulty = topic.difficulty
        
        # Get questions
        # Beginner: 3, Intermediate: 4, Advanced: 5
        limit = 3
        if difficulty == 2:
            limit = 4
        elif difficulty == 3:
            limit = 5

        questions = get_questions_for_topic(db_session, topic_id, difficulty=difficulty, limit=limit)
        
        if not questions:
            flash("No quiz questions available for this topic yet.", "warning")
            return redirect(url_for("dashboard"))

        session["quiz_questions"] = [q.id for q in questions]
        session["quiz_answers"] = {}
        session["quiz_index"] = 0
        session["quiz_topic_id"] = topic_id

    question_ids = session["quiz_questions"]
    q_index = int(request.args.get("q", session.get("quiz_index", 0)))
    
    if q_index >= len(question_ids):
        # Fail safe
        return redirect(url_for("dashboard"))

    session["quiz_index"] = q_index

    # Handle submission POST
    if request.method == "POST":
        selected = request.form.get("selected_option")
        if not selected:
            # Re-render same page with error
            flash("Please select an option before proceeding.", "warning")
            return redirect(url_for("quiz", topic_id=topic_id, q=q_index))

        # Store answer
        q_id_str = str(question_ids[q_index])
        answers = session.get("quiz_answers", {})
        answers[q_id_str] = selected
        session["quiz_answers"] = answers

        # Check if last question
        if q_index + 1 >= len(question_ids):
            # Grade quiz!
            submission_dict = {int(k): v for k, v in answers.items()}
            results, recommendation = grade_quiz_submission(db_session, topic_id, submission_dict)
            
            # Save results to session
            session["last_results"] = results
            session["last_recommendation"] = recommendation
            
            # Clear quiz progress session keys
            session.pop("quiz_questions", None)
            session.pop("quiz_answers", None)
            session.pop("quiz_index", None)
            session.pop("quiz_topic_id", None)
            
            return redirect(url_for("results"))
        else:
            # Advance to next question
            return redirect(url_for("quiz", topic_id=topic_id, q=q_index + 1))

    # GET Request
    question = db_session.get(QuizQuestion, question_ids[q_index])
    progress_percent = int((q_index / len(question_ids)) * 100)
    current_focus = get_current_focus()

    return render_template(
        "quiz.html",
        topic=topic,
        question=question,
        q_index=q_index,
        q_count=len(question_ids),
        progress_percent=progress_percent,
        is_last=(q_index + 1 == len(question_ids)),
        current_focus=current_focus,
        active_tab="lesson"
    )


@app.route("/results")
def results():
    """
    Render results of the most recently submitted quiz.
    """
    results_data = session.get("last_results")
    recommendation = session.get("last_recommendation")
    
    if not results_data or not recommendation:
        return redirect(url_for("dashboard"))

    # Find the next recommended video lesson ID to display as CTA
    rec_topic_name = recommendation.get("next_topic")
    next_video_id = None
    
    if rec_topic_name:
        rec_topic = db_session.query(Topic).filter_by(name=rec_topic_name).first()
        if rec_topic:
            # Find first unwatched video in recommended topic
            unwatched = (
                db_session.query(Video)
                .outerjoin(LearningSession, Video.id == LearningSession.video_id)
                .filter(Video.topic_id == rec_topic.id)
                .filter((LearningSession.watched == False) | (LearningSession.watched == None))
                .order_by(Video.order_in_topic)
                .first()
            )
            if unwatched:
                next_video_id = unwatched.id
            else:
                # If all watched, default to first video of that topic
                first_vid = db_session.query(Video).filter_by(topic_id=rec_topic.id).order_by(Video.order_in_topic).first()
                if first_vid:
                    next_video_id = first_vid.id

    current_focus = get_current_focus()

    return render_template(
        "results.html",
        results=results_data,
        recommendation=recommendation,
        next_video_id=next_video_id,
        current_focus=current_focus,
        active_tab="lesson"
    )


@app.route("/progress")
def progress():
    """
    Render the student's progress and analytics dashboard.
    """
    # 1. Calculate topic masteries using Pandas
    topics = calculate_topic_mastery(db_session)
    
    # 2. Calculate overall mastery percentage
    overall_mastery = 0
    completed_topics_count = 0
    
    if topics:
        total_mastery = sum(t["mastery_percentage"] for t in topics)
        overall_mastery = int(total_mastery / len(topics))
        completed_topics_count = sum(1 for t in topics if t["status"] == "Mastered")
        
    # 3. Calculate score trend using NumPy
    trend_status, trend_slope = calculate_score_trend(db_session)
    
    # 4. Generate Matplotlib performance chart
    static_dir = os.path.join(app.root_path, "static")
    has_attempts = db_session.query(QuizAttempt).count() > 0
    
    if has_attempts:
        generate_progress_chart(db_session, static_dir)
        
    current_focus = get_current_focus()

    return render_template(
        "progress.html",
        topics=topics,
        overall_mastery=overall_mastery,
        completed_topics_count=completed_topics_count,
        trend_status=trend_status,
        has_chart=has_attempts,
        current_focus=current_focus,
        timestamp=int(time.time()),  # For cache-busting the image
        active_tab="progress"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
