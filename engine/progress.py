"""
Progress analytics engine.
Computes topic mastery using Pandas, calculates performance trends using NumPy,
and generates a dark-themed Matplotlib progress chart.
"""

import os
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np
import matplotlib
# Use non-interactive backend for server environments
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sqlalchemy import func, Integer
from sqlalchemy.orm import Session
from database.models import Topic, Video, QuizAttempt, QuizQuestion, LearningSession


def calculate_topic_mastery(session: Session) -> List[Dict[str, Any]]:
    """
    Calculate the mastery percentage for each topic using Pandas.
    Mastery is a weighted average of:
    - Video watched progress (50%)
    - Highest quiz score (50%)

    Args:
        session (Session): Database session.

    Returns:
        List[Dict[str, Any]]: List of topics with calculated mastery percentages and stats.
    """
    topics = session.query(Topic).all()
    if not topics:
        return []

    # 1. Load topics, videos, and learning sessions into list of dicts
    videos = session.query(Video).all()
    sessions = session.query(LearningSession).all()

    # Convert to DataFrames
    df_topics = pd.DataFrame([{
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "difficulty": t.difficulty
    } for t in topics])

    if len(videos) == 0:
        # If no videos, set mastery to 0.0
        df_topics["mastery_percentage"] = 0.0
        df_topics["video_progress"] = 0.0
        df_topics["quiz_score"] = 0.0
        df_topics["status"] = "Locked"
        return df_topics.to_dict(orient="records")

    df_videos = pd.DataFrame([{
        "id": v.id,
        "topic_id": v.topic_id,
        "subtopic": v.subtopic
    } for v in videos])

    df_sessions = pd.DataFrame([{
        "video_id": s.video_id,
        "topic_id": s.topic_id,
        "watched": s.watched
    } for s in sessions]) if sessions else pd.DataFrame(columns=["video_id", "topic_id", "watched"])

    # Calculate video completion rate per topic
    if not df_sessions.empty:
        # Group by topic and calculate watched ratio
        video_stats = df_sessions.groupby("topic_id")["watched"].agg(["count", "sum"]).reset_index()
        video_stats["video_progress"] = (video_stats["sum"] / video_stats["count"]) * 100.0
    else:
        video_stats = pd.DataFrame(columns=["topic_id", "video_progress"])

    # 2. Load quiz attempts and questions
    attempts = session.query(QuizAttempt).all()
    questions = session.query(QuizQuestion).all()

    if attempts and questions:
        df_questions = pd.DataFrame([{
            "id": q.id,
            "topic_id": q.topic_id
        } for q in questions])

        df_attempts = pd.DataFrame([{
            "question_id": a.question_id,
            "is_correct": a.is_correct,
            "attempt_group_id": a.attempt_group_id
        } for a in attempts])

        # Merge attempts with questions to get topic_id
        df_attempts_merged = pd.merge(df_attempts, df_questions, left_on="question_id", right_on="id")

        # Group by attempt_group_id and topic_id to get score per quiz attempt
        scores_per_attempt = df_attempts_merged.groupby(["attempt_group_id", "topic_id"])["is_correct"].agg(["count", "sum"]).reset_index()
        scores_per_attempt["score"] = (scores_per_attempt["sum"] / scores_per_attempt["count"]) * 100.0

        # Get the highest score for each topic
        quiz_stats = scores_per_attempt.groupby("topic_id")["score"].max().reset_index()
        quiz_stats.rename(columns={"score": "quiz_score"}, inplace=True)
    else:
        quiz_stats = pd.DataFrame(columns=["topic_id", "quiz_score"])

    # 3. Merge all stats back to topics
    df_merged = pd.merge(df_topics, video_stats, left_on="id", right_on="topic_id", how="left")
    df_merged = pd.merge(df_merged, quiz_stats, left_on="id", right_on="topic_id", how="left")

    df_merged["video_progress"] = df_merged["video_progress"].fillna(0.0)
    df_merged["quiz_score"] = df_merged["quiz_score"].fillna(0.0)

    # Compute Overall Mastery: 50% video progress + 50% quiz score
    df_merged["mastery_percentage"] = (df_merged["video_progress"] * 0.5) + (df_merged["quiz_score"] * 0.5)
    df_merged["mastery_percentage"] = df_merged["mastery_percentage"].round(1)

    # Add descriptive status
    # Determine statuses based on completion rates
    statuses = []
    for idx, row in df_merged.iterrows():
        # Check prerequisites
        prereq_met = True
        # For simplicity, if the topic index is 0, no prerequisites.
        # Otherwise, the previous topic must have mastery > 80% to unlock.
        if idx > 0:
            prev_row = df_merged.iloc[idx - 1]
            if prev_row["mastery_percentage"] < 80.0:
                prereq_met = False

        if not prereq_met:
            statuses.append("Locked")
        elif row["mastery_percentage"] == 100.0:
            statuses.append("Mastered")
        elif row["mastery_percentage"] > 0.0 or row["video_progress"] > 0.0:
            statuses.append("In Progress")
        else:
            statuses.append("Unlocked")

    df_merged["status"] = statuses

    # Save calculated masteries back to the SQL database
    for idx, row in df_merged.iterrows():
        t = session.get(Topic, int(row["id"]))
        if t:
            t.mastery_percentage = float(row["mastery_percentage"])
    session.commit()

    return df_merged.to_dict(orient="records")


def calculate_score_trend(session: Session) -> Tuple[str, float]:
    """
    Calculate the student's performance trend across all quiz sessions using NumPy.
    Fits a linear regression line (polyfit) to the quiz score history.

    Args:
        session (Session): Database session.

    Returns:
        Tuple[str, float]:
            - Trend status: "improving", "declining", or "stable"
            - Slope of the score progression
    """
    # Group attempts by attempt_group_id to calculate the score of each quiz attempt in order
    attempts_grouped = (
        session.query(
            QuizAttempt.attempt_group_id,
            func.count(QuizAttempt.id).label("total"),
            func.sum(func.cast(QuizAttempt.is_correct, Integer)).label("correct"),
            func.max(QuizAttempt.timestamp).label("time")
        )
        .group_by(QuizAttempt.attempt_group_id)
        .order_by(func.max(QuizAttempt.timestamp).asc())
        .all()
    )

    if len(attempts_grouped) < 2:
        return "stable", 0.0

    scores = []
    for group in attempts_grouped:
        total = group.total
        correct = group.correct if group.correct is not None else 0
        percentage = (correct / total) * 100.0 if total > 0 else 0.0
        scores.append(percentage)

    # Use NumPy to fit a linear line (y = mx + c)
    y = np.array(scores)
    x = np.arange(len(scores))

    # Calculate slope (m)
    slope, intercept = np.polyfit(x, y, 1)

    if slope > 1.0:
        trend = "improving"
    elif slope < -1.0:
        trend = "declining"
    else:
        trend = "stable"

    return trend, float(round(slope, 2))


def generate_progress_chart(session: Session, output_dir: str) -> str:
    """
    Generate a quiz accuracy timeline chart using Matplotlib and save as static asset.
    Styled according to the premium dark developer theme.

    Args:
        session (Session): Database session.
        output_dir (str): Directory where the chart image should be saved.

    Returns:
        str: Absolute file path to the saved chart.
    """
    attempts_grouped = (
        session.query(
            QuizAttempt.attempt_group_id,
            func.count(QuizAttempt.id).label("total"),
            func.sum(func.cast(QuizAttempt.is_correct, Integer)).label("correct"),
            func.max(QuizAttempt.timestamp).label("time")
        )
        .group_by(QuizAttempt.attempt_group_id)
        .order_by(func.max(QuizAttempt.timestamp).asc())
        .all()
    )

    scores = []
    labels = []
    for idx, group in enumerate(attempts_grouped):
        total = group.total
        correct = group.correct if group.correct is not None else 0
        percentage = (correct / total) * 100.0 if total > 0 else 0.0
        scores.append(percentage)
        labels.append(f"Q{idx + 1}")

    if not scores:
        # Empty placeholder state if no scores yet
        scores = [0.0]
        labels = ["Start"]

    # Set up dark theme aesthetic configurations
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(6, 4), facecolor='#0f1117')
    ax.set_facecolor('#161b22')

    # Plot line and points
    # Electric blue: #508ff8
    ax.plot(labels, scores, color='#508ff8', linewidth=2.5, marker='o', 
            markersize=8, markerfacecolor='#0b0e14', markeredgecolor='#508ff8', 
            markeredgewidth=2, label='Quiz Accuracy')

    # Fill area under the curve
    if len(scores) > 1:
        ax.fill_between(labels, scores, color='#508ff8', alpha=0.1)

    # Y-axis bounds and styling
    ax.set_ylim(-5, 105)
    ax.set_ylabel('Accuracy (%)', color='#e1e2eb', fontsize=10, fontweight='bold')
    ax.tick_params(colors='#8c909e', labelsize=9)

    # Grid and borders
    ax.grid(True, color='#30363d', linestyle='--', alpha=0.5)
    
    # Hide top and right spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#30363d')
    ax.spines['bottom'].set_color('#30363d')

    plt.title('Quiz Performance Timeline', color='#e1e2eb', fontsize=12, fontweight='bold', pad=15)
    plt.tight_layout()

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    chart_path = os.path.join(output_dir, 'progress_chart.png')
    
    plt.savefig(chart_path, dpi=150, facecolor='#0f1117', bbox_inches='tight')
    plt.close()

    return chart_path
