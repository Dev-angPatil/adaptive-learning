"""
Quiz engine module.
Handles fetching questions by topic/difficulty, grading user answers,
saving attempts to the database, and triggering the adaptive engine.
"""

import uuid
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from database.models import QuizQuestion, QuizAttempt, Topic
from engine.adaptive import get_recommendation


def get_questions_for_topic(
    session: Session,
    topic_id: int,
    difficulty: int = 1,
    limit: int = 3
) -> List[QuizQuestion]:
    """
    Fetch quiz questions for a specific topic, filtering by difficulty.
    If not enough questions of specified difficulty exist, falls back to other difficulties.

    Args:
        session (Session): Database session.
        topic_id (int): ID of the topic.
        difficulty (int): Desired difficulty level (1-3).
        limit (int): Number of questions to return.

    Returns:
        List[QuizQuestion]: List of question records.
    """
    # 1. Try to get questions of the exact difficulty first
    questions = (
        session.query(QuizQuestion)
        .filter_by(topic_id=topic_id, difficulty=difficulty)
        .limit(limit)
        .all()
    )

    # 2. If not enough questions, fetch other difficulties for this topic
    if len(questions) < limit:
        needed = limit - len(questions)
        existing_ids = [q.id for q in questions]
        fallback_questions = (
            session.query(QuizQuestion)
            .filter(QuizQuestion.topic_id == topic_id, ~QuizQuestion.id.in_(existing_ids))
            .limit(needed)
            .all()
        )
        questions.extend(fallback_questions)

    # 3. If still not enough, fetch any questions from the database as absolute fallback
    if len(questions) < limit:
        needed = limit - len(questions)
        existing_ids = [q.id for q in questions]
        fallback_questions = (
            session.query(QuizQuestion)
            .filter(~QuizQuestion.id.in_(existing_ids))
            .limit(needed)
            .all()
        )
        questions.extend(fallback_questions)

    return questions[:limit]


def grade_quiz_submission(
    session: Session,
    topic_id: int,
    submission: Dict[int, str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Grade a student's quiz submission, store attempts, and run the adaptive engine.

    Args:
        session (Session): Database session.
        topic_id (int): ID of the topic.
        submission (Dict[int, str]): Dict of question ID -> selected answer (e.g. {1: 'A', 2: 'C'}).

    Returns:
        Tuple[Dict[str, Any], Dict[str, Any]]:
            - Graded results summary (correct, total, percentage, list of details).
            - Adaptive engine recommendation details.
    """
    correct_count = 0
    total_count = len(submission)
    attempt_group_id = str(uuid.uuid4())
    graded_details = []

    for q_id, selected in submission.items():
        question = session.get(QuizQuestion, q_id)
        if not question:
            continue

        # Case-insensitive comparison of single character answers
        is_correct = (selected.strip().upper() == question.correct_answer.strip().upper())
        if is_correct:
            correct_count += 1

        # Record attempt
        attempt = QuizAttempt(
            question_id=q_id,
            selected_answer=selected.strip().upper(),
            is_correct=is_correct,
            attempt_group_id=attempt_group_id
        )
        session.add(attempt)

        graded_details.append({
            "question_id": q_id,
            "question_text": question.question_text,
            "selected_answer": selected,
            "correct_answer": question.correct_answer,
            "is_correct": is_correct,
            "options": {
                "A": question.option_a,
                "B": question.option_b,
                "C": question.option_c,
                "D": question.option_d
            }
        })

    session.commit()

    score_percentage = (correct_count / total_count) * 100.0 if total_count > 0 else 0.0

    # 1. Update Topic Mastery Percentage
    # Formula: we can update the topic's mastery. If the user got 100% on the quiz, topic mastery is 100%.
    # If they got a score, we can set topic mastery to the max of current mastery or this score.
    topic = session.get(Topic, topic_id)
    if topic:
        # Update topic mastery. If they passed with > 80%, let's make it 100% or progress.
        # Let's say topic mastery is set to the maximum of its current mastery and the quiz score.
        topic.mastery_percentage = max(topic.mastery_percentage, score_percentage)
        session.commit()

    # 2. Query Adaptive Engine for recommendation
    recommendation = get_recommendation(
        session=session,
        current_topic_id=topic_id,
        correct_count=correct_count,
        total_count=total_count
    )

    results_summary = {
        "attempt_group_id": attempt_group_id,
        "topic_id": topic_id,
        "topic_name": topic.name if topic else "General Python",
        "correct_count": correct_count,
        "total_count": total_count,
        "score_percentage": round(score_percentage, 1),
        "details": graded_details
    }

    return results_summary, recommendation
