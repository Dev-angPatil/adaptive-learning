"""
Adaptive engine module.
Interfaces with Claude API to recommend next topics, difficulties, and depth levels
based on the student's history, with a programmatic fallback.
"""

import os
import json
import re
from typing import List, Dict, Any

from dotenv import load_dotenv
from sqlalchemy import func, Integer
from sqlalchemy.orm import Session
from database.models import Topic, Video, QuizQuestion, QuizAttempt

# Load environment variables
load_dotenv()


def extract_json_from_text(text: str) -> str:
    """
    Utility to strip markdown wrappers and extract raw JSON content.

    Args:
        text (str): Raw string with potential markdown code blocks.

    Returns:
        str: Clean JSON string.
    """
    pattern = re.compile(r'```(?:json)?\s*(.*?)\s*```', re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def run_rule_based_adaptive(
    current_topic_name: str,
    score_percentage: float,
    all_topics: List[Dict[str, Any]],
    history: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Programmatic rule-based adaptive logic fallback.

    Args:
        current_topic_name (str): Current topic name.
        score_percentage (float): Score as percentage (0-100).
        all_topics (List[Dict[str, Any]]): List of all curriculum topics.
        history (List[Dict[str, Any]]): Quiz attempt history.

    Returns:
        Dict[str, Any]: Decision dict matching the JSON schema.
    """
    # 1. Find index of current topic
    current_idx = -1
    for i, t in enumerate(all_topics):
        if t["name"] == current_topic_name:
            current_idx = i
            break

    # If current topic not found, default to first topic
    if current_idx == -1:
        current_idx = 0
        current_topic_name = all_topics[0]["name"] if all_topics else "Basic Syntax"

    current_topic = all_topics[current_idx] if all_topics else {"difficulty": 1}
    current_diff = current_topic.get("difficulty", 1)

    # 2. Adaptive logic based on score
    if score_percentage < 50.0:
        # Score is low: review current topic, decrease difficulty if possible
        next_topic = current_topic_name
        next_difficulty = max(1, current_diff - 1)
        next_depth = 1
        recommendation_label = f"Reviewing {current_topic_name}"
        reasoning = (
            f"Your score of {score_percentage:.1f}% indicates that some fundamental concepts "
            f"in '{current_topic_name}' need reinforcement. We recommend reviewing the videos "
            f"and retrying the quiz at difficulty level {next_difficulty} to build solid foundations before moving forward."
        )
    elif score_percentage <= 80.0:
        # Score is moderate: continue in topic or advance with caution
        next_topic = current_topic_name
        next_difficulty = current_diff
        next_depth = 2
        recommendation_label = f"Reinforcing {current_topic_name}"
        reasoning = (
            f"Great effort! You achieved {score_percentage:.1f}% on the quiz. You have a good grasp of the basics of "
            f"'{current_topic_name}', but we recommend reviewing specific subtopics to solidify your understanding "
            f"at difficulty level {next_difficulty} before tackling advanced concepts."
        )
    else:
        # Score is high: advance to next topic or increase difficulty
        if current_idx + 1 < len(all_topics):
            next_topic = all_topics[current_idx + 1]["name"]
            next_difficulty = all_topics[current_idx + 1]["difficulty"]
            next_depth = 1
            recommendation_label = f"Advancing to {next_topic}"
            reasoning = (
                f"Excellent job! With a score of {score_percentage:.1f}%, you have mastered '{current_topic_name}'. "
                f"The adaptive engine is advancing you to the next topic, '{next_topic}', starting at difficulty level {next_difficulty}."
            )
        else:
            # Reached the end of the curriculum!
            next_topic = current_topic_name
            next_difficulty = current_diff
            next_depth = 3
            recommendation_label = "Curriculum Mastered!"
            reasoning = (
                f"Spectacular! You scored {score_percentage:.1f}% on the final topic. You have successfully completed "
                "all available topics in the curriculum! Feel free to review any previous lessons or explore challenges."
            )

    return {
        "next_topic": next_topic,
        "difficulty": next_difficulty,
        "depth_level": next_depth,
        "reasoning": reasoning,
        "recommendation_label": recommendation_label
    }


def get_recommendation(
    session: Session,
    current_topic_id: int,
    correct_count: int,
    total_count: int
) -> Dict[str, Any]:
    """
    Decide the next learning recommendation using Claude API, or fallback to rule-based logic.

    Args:
        session (Session): Database session.
        current_topic_id (int): ID of the topic just tested.
        correct_count (int): Number of correct answers in the latest quiz.
        total_count (int): Total number of questions in the latest quiz.

    Returns:
        Dict[str, Any]: Recommendation decision details.
    """
    # 1. Fetch current topic details
    current_topic = session.get(Topic, current_topic_id)
    if not current_topic:
        raise ValueError(f"Topic ID {current_topic_id} not found in database.")

    score_percentage = (correct_count / total_count) * 100.0 if total_count > 0 else 0.0

    # 2. Get list of all topics in order to pass to Claude or Rule-based
    topics_list = session.query(Topic).order_by(Topic.id).all()
    all_topics_data = [
        {"name": t.name, "description": t.description, "difficulty": t.difficulty}
        for t in topics_list
    ]

    # 3. Fetch all previous quiz attempts to compile history
    # Group attempts by attempt_group_id
    attempts_grouped = (
        session.query(
            QuizAttempt.attempt_group_id,
            QuizQuestion.topic_id,
            Topic.name.label("topic_name"),
            func.count(QuizAttempt.id).label("total"),
            func.sum(func.cast(QuizAttempt.is_correct, Integer)).label("correct"),
            func.max(QuizAttempt.timestamp).label("time")
        )
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .join(Topic, QuizQuestion.topic_id == Topic.id)
        .group_by(QuizAttempt.attempt_group_id, QuizQuestion.topic_id, Topic.name)
        .order_by(func.max(QuizAttempt.timestamp).desc())
        .all()
    )

    history_data = []
    for g in attempts_grouped:
        tot = g.total
        corr = g.correct if g.correct is not None else 0
        perc = (corr / tot) * 100.0 if tot > 0 else 0.0
        history_data.append({
            "topic_name": g.topic_name,
            "correct_answers": corr,
            "total_questions": tot,
            "score_percentage": round(perc, 1),
            "timestamp": g.time.strftime("%Y-%m-%d %H:%M:%S") if g.time else ""
        })

    # If GEMINI_API_KEY is not defined, run rule-based fallback immediately
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ADAPTIVE ENGINE] GEMINI_API_KEY not found. Running rule-based adaptive engine.")
        return run_rule_based_adaptive(current_topic.name, score_percentage, all_topics_data, history_data)

    # 4. Prompt Gemini API
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        topics_info_str = json.dumps(all_topics_data, indent=2)
        history_info_str = json.dumps(history_data, indent=2)

        prompt = f"""
You are the AI Adaptive Brain of a Python learning platform.
Your job is to analyze the student's quiz history and decide what they should study next: the next topic, difficulty level, and depth level.

Available topics in the curriculum:
{topics_info_str}

Student Quiz History (most recent first):
{history_info_str}

Most Recent Quiz:
Topic: {current_topic.name}
Score: {score_percentage:.1f}% ({correct_count}/{total_count} correct)

Based on this history, recommend the next step for the student.
You must return a valid JSON object matching the following structure:
{{
  "next_topic": "string",
  "difficulty": 1 | 2 | 3,
  "depth_level": 1 | 2 | 3,
  "reasoning": "string",
  "recommendation_label": "string"
}}

Guidelines:
1. `next_topic`: Must match one of the available topic names, or be the current topic name if they need to review.
2. `difficulty`: Recommend 1 (Beginner), 2 (Intermediate), or 3 (Advanced).
3. `depth_level`: Recommend 1, 2, or 3.
4. `reasoning`: A full paragraph explaining your pedagogical reasoning (e.g. why they should review, what topics they struggled with, or what advanced concept they are ready for).
5. `recommendation_label`: A short, actionable label (e.g., "Reviewing Functions", "Advancing to Lists & Tuples", "Reviewing Lists").

Return ONLY the JSON string. Do not include any conversational filler, markdown formatting (other than a code block wrapper if necessary, but raw JSON is preferred), or text outside the JSON object.
"""

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(prompt)
        content = response.text
        json_str = extract_json_from_text(content)
        result = json.loads(json_str)

        # Validate that the next_topic is valid
        valid_topics = [t["name"] for t in all_topics_data]
        if result.get("next_topic") not in valid_topics:
            # Correct next topic to current topic if invalid topic name returned
            result["next_topic"] = current_topic.name

        return result

    except Exception as e:
        print(f"[ADAPTIVE ENGINE] Gemini API call failed: {e}. Falling back to rule-based engine.")
        return run_rule_based_adaptive(current_topic.name, score_percentage, all_topics_data, history_data)
