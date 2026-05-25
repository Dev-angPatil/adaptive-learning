"""
YouTube Playlist Pipeline script.
Extracts YouTube metadata, calls Claude API to parse/validate curriculum metadata
and generate quiz questions, then saves everything to SQLite.
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add current directory to path so database package can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import Base, Topic, Video, QuizQuestion, QuizAttempt, LearningSession
from content.curriculum import STARTER_CURRICULUM

# Load environment variables
load_dotenv()


def parse_iso8601_duration(duration_str: str) -> int:
    """
    Parse an ISO 8601 duration string (like PT15M33S) into minutes (rounded).

    Args:
        duration_str (str): ISO 8601 duration.

    Returns:
        int: Duration in minutes.
    """
    pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    match = pattern.match(duration_str)
    if not match:
        return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0

    total_minutes = hours * 60 + minutes + (1 if seconds >= 30 else 0)
    return max(1, total_minutes)


def get_playlist_id(url: str) -> str:
    """
    Extract playlist ID from a YouTube playlist URL.

    Args:
        url (str): YouTube playlist URL.

    Returns:
        str: Playlist ID.
    """
    import urllib.parse as urlparse
    parsed = urlparse.urlparse(url)
    captured = urlparse.parse_qs(parsed.query)
    if 'list' in captured:
        return captured['list'][0]
    if len(url) > 20 and '/' not in url:
        return url
    raise ValueError("Invalid YouTube URL. Could not find 'list' query parameter.")


def fetch_youtube_videos(playlist_url: str) -> List[Dict[str, Any]]:
    """
    Fetch metadata (title, description, duration) of all videos in the playlist using yt-dlp.

    Args:
        playlist_url (str): YouTube playlist URL.

    Returns:
        List[Dict[str, Any]]: List of video details.
    """
    import yt_dlp

    print(f"Extracting playlist info from: {playlist_url} using yt-dlp...")
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,  # True prevents bot-detection blocks on individual videos
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            playlist_dict = ydl.extract_info(playlist_url, download=False)
    except Exception as e:
        raise ValueError(f"Failed to extract playlist metadata using yt-dlp: {e}")

    if not playlist_dict:
        raise ValueError("Could not retrieve playlist metadata. Playlist might be private or invalid.")

    entries = playlist_dict.get('entries', [])
    videos = []

    for entry in entries:
        if not entry:
            continue
        v_id = entry.get('id')
        duration_seconds = entry.get('duration') or 0
        # Convert to minutes (minimum 1)
        duration_minutes = max(1, int(duration_seconds / 60))

        videos.append({
            'youtube_url': f"https://www.youtube.com/watch?v={v_id}",
            'title': entry.get('title', ''),
            'description': entry.get('description') or '',
            'id': v_id,
            'duration_minutes': duration_minutes
        })

    print(f"Successfully retrieved {len(videos)} videos from YouTube playlist using yt-dlp.")
    return videos


def extract_json_from_text(text: str) -> str:
    """
    Find and return JSON substring within Claude's response.

    Args:
        text (str): Raw response text.

    Returns:
        str: JSON substring.
    """
    pattern = re.compile(r'```(?:json)?\s*(.*?)\s*```', re.DOTALL)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def query_gemini_for_metadata(video: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send video details to Gemini API to classify and generate quiz questions.

    Args:
        video (Dict[str, Any]): Video details dict.

    Returns:
        Dict[str, Any]: Categorized metadata + quiz questions.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    prompt = f"""
You are a Python curriculum design assistant. You are given a video title, description, and duration from a YouTube playlist.
Your job is to analyze this video and classify it into our adaptive learning taxonomy, as well as generate quiz questions.

Input Video Metadata:
Title: {video['title']}
Description: {video['description']}
Duration: {video['duration_minutes']} minutes

Your output MUST be a valid JSON object matching this structure:
{{
  "topic_name": "string",
  "subtopic": "string",
  "difficulty": 1 | 2 | 3,
  "depth_level": 1 | 2 | 3,
  "duration_minutes": {video['duration_minutes']},
  "prerequisites": ["string"],
  "order_in_topic": 1,
  "description": "string",
  "quiz_questions": [
    {{
      "question_text": "string",
      "option_a": "string",
      "option_b": "string",
      "option_c": "string",
      "option_d": "string",
      "correct_answer": "A" | "B" | "C" | "D",
      "difficulty": 1 | 2 | 3
    }}
  ]
}}

Guidelines for fields:
1. `topic_name`: The broad category this video belongs to (e.g. "Basic Syntax", "Functions", "Lists & Tuples", "Classes (OOP)"). Keep names consistent across different videos.
2. `subtopic`: A specific, clear name for this video's focus (e.g., "List Slicing").
3. `difficulty`: 1 (Beginner), 2 (Intermediate), 3 (Advanced).
4. `depth_level`: 1 (Foundational concept), 2 (Practical application), 3 (Advanced/nuanced edge-cases).
5. `duration_minutes`: Use the provided duration or estimate if necessary.
6. `prerequisites`: List of subtopic names or topic names that must be learned BEFORE watching this video. If none, return an empty array [].
7. `order_in_topic`: The logical 1-based order index of this video within its topic (e.g. 1 for the first introductory video, 2 for the next, etc.).
8. `description`: A clean, developer-focused 1-2 sentence description of what the video covers.
9. `quiz_questions`: Generate multiple-choice quiz questions based on the content. The number of questions should vary by difficulty:
   - 3 questions if difficulty is 1 (Beginner)
   - 4 questions if difficulty is 2 (Intermediate)
   - 5 questions if difficulty is 3 (Advanced)
   Each question must have exactly 4 choices (option_a, option_b, option_c, option_d) and a single correct option index ('A', 'B', 'C', or 'D'). Questions must test the concepts taught. Make sure option keys are correct.

Return ONLY the JSON string. Do not include any conversational filler, markdown formatting (other than a code block wrapper if necessary, but raw JSON is preferred), or text outside the JSON object.
"""

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )
    response = model.generate_content(prompt)
    content = response.text
    json_str = extract_json_from_text(content)
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response from Gemini: {e}")
        print(f"Raw output: {content}")
        # Return fallback metadata if parsing fails
        return {
            "topic_name": "General Python",
            "subtopic": video['title'],
            "difficulty": 1,
            "depth_level": 1,
            "duration_minutes": video['duration_minutes'],
            "prerequisites": [],
            "order_in_topic": 1,
            "description": video['description'][:200],
            "quiz_questions": [
                {
                    "question_text": f"What is the focus of the video '{video['title']}'?",
                    "option_a": "Python Syntax",
                    "option_b": "Data Engineering",
                    "option_c": "Web Development",
                    "option_d": "None of the above",
                    "correct_answer": "A",
                    "difficulty": 1
                }
            ]
        }


def save_to_database(metadata_list: List[Dict[str, Any]], youtube_urls: List[str], session) -> None:
    """
    Save the extracted metadata and quiz questions to SQLite.

    Args:
        metadata_list (List[Dict[str, Any]]): Metadata lists.
        youtube_urls (List[str]): Original YouTube URLs.
        session: SQLAlchemy session.
    """
    print("Saving pipeline results to database...")

    # Clear existing to avoid duplicate conflicts if running fresh
    session.query(QuizAttempt).delete()
    session.query(LearningSession).delete()
    session.query(QuizQuestion).delete()
    session.query(Video).delete()
    session.query(Topic).delete()
    session.commit()

    topic_cache = {}

    for idx, meta in enumerate(metadata_list):
        topic_name = meta.get("topic_name", "General Python")
        
        # 1. Create topic if it does not exist
        if topic_name not in topic_cache:
            topic = session.query(Topic).filter_by(name=topic_name).first()
            if not topic:
                topic = Topic(
                    name=topic_name,
                    description=f"Core concepts about {topic_name}.",
                    difficulty=meta.get("difficulty", 1),
                    mastery_percentage=0.0
                )
                session.add(topic)
                session.flush()
            topic_cache[topic_name] = topic
        else:
            topic = topic_cache[topic_name]

        # 2. Add video
        video = Video(
            topic_name=topic_name,
            subtopic=meta.get("subtopic", "Subtopic"),
            difficulty=meta.get("difficulty", 1),
            depth_level=meta.get("depth_level", 1),
            duration_minutes=meta.get("duration_minutes", 10),
            order_in_topic=meta.get("order_in_topic", 1),
            description=meta.get("description", ""),
            youtube_url=youtube_urls[idx],
            topic_id=topic.id
        )
        video.prerequisites = meta.get("prerequisites", [])
        session.add(video)
        session.flush()

        # 3. Create uncompleted LearningSession
        session.add(LearningSession(
            topic_id=topic.id,
            video_id=video.id,
            watched=False,
            timestamp=datetime.utcnow()
        ))

        # 4. Add quiz questions
        questions = meta.get("quiz_questions", [])
        for q in questions:
            question = QuizQuestion(
                question_text=q.get("question_text", ""),
                option_a=q.get("option_a", ""),
                option_b=q.get("option_b", ""),
                option_c=q.get("option_c", ""),
                option_d=q.get("option_d", ""),
                correct_answer=q.get("correct_answer", "A"),
                difficulty=q.get("difficulty", 1),
                topic_id=topic.id
            )
            session.add(question)
    session.flush()
    # Add a few mock quiz attempts so that the progress chart renders immediately
    all_questions = session.query(QuizQuestion).all()
    if all_questions:
        from collections import defaultdict
        topic_questions = defaultdict(list)
        for q in all_questions:
            topic_questions[q.topic_id].append(q)
        
        # Add a couple of mock attempts across topics
        for t_idx, (t_id, qs) in enumerate(topic_questions.items()):
            if not qs:
                continue
            # Attempt 1: got ~66% correct
            attempt_group_1 = f"mock_pipeline_attempt_{t_id}_1"
            for q_idx, q in enumerate(qs):
                is_correct = (q_idx % 3 != 0)
                session.add(QuizAttempt(
                    question_id=q.id,
                    selected_answer=q.correct_answer if is_correct else ("B" if q.correct_answer != "B" else "A"),
                    is_correct=is_correct,
                    timestamp=datetime.utcnow() - timedelta(days=2),
                    attempt_group_id=attempt_group_1
                ))
            
            # Attempt 2 (only for the first topic, showing improvement)
            if t_idx == 0:
                attempt_group_2 = f"mock_pipeline_attempt_{t_id}_2"
                for q in qs:
                    session.add(QuizAttempt(
                        question_id=q.id,
                        selected_answer=q.correct_answer,
                        is_correct=True,
                        timestamp=datetime.utcnow() - timedelta(days=1),
                        attempt_group_id=attempt_group_2
                    ))

    session.commit()
    print("Database updated successfully.")


def seed_mock_data(session) -> None:
    """
    Helper function to seed mock curriculum.
    """
    from content.curriculum import STARTER_CURRICULUM
    from datetime import datetime, timedelta

    # Clean DB
    session.query(QuizAttempt).delete()
    session.query(LearningSession).delete()
    session.query(QuizQuestion).delete()
    session.query(Video).delete()
    session.query(Topic).delete()
    session.commit()

    topic_map = {}
    for item in STARTER_CURRICULUM:
        t_data = item["topic"]
        topic = Topic(
            name=t_data["name"],
            description=t_data["description"],
            difficulty=t_data["difficulty"],
            mastery_percentage=t_data["mastery_percentage"]
        )
        session.add(topic)
        session.flush()
        topic_map[topic.name] = topic.id

        # Add Videos
        for v_data in item["videos"]:
            video = Video(
                topic_name=topic.name,
                subtopic=v_data["subtopic"],
                difficulty=v_data["difficulty"],
                depth_level=v_data["depth_level"],
                duration_minutes=v_data["duration_minutes"],
                order_in_topic=v_data["order_in_topic"],
                description=v_data["description"],
                youtube_url=v_data["youtube_url"],
                topic_id=topic.id
            )
            video.prerequisites = v_data["prerequisites"]
            session.add(video)
            session.flush()

            # Watched status simulator
            watched = True if topic.mastery_percentage == 100.0 else False
            if topic.name == "Lists & Tuples" and v_data["order_in_topic"] == 1:
                watched = True
            
            session.add(LearningSession(
                topic_id=topic.id,
                video_id=video.id,
                watched=watched,
                timestamp=datetime.utcnow() - timedelta(days=2)
            ))

        # Add Quiz Questions
        for q_data in item["questions"]:
            question = QuizQuestion(
                question_text=q_data["question_text"],
                option_a=q_data["option_a"],
                option_b=q_data["option_b"],
                option_c=q_data["option_c"],
                option_d=q_data["option_d"],
                correct_answer=q_data["correct_answer"],
                difficulty=q_data["difficulty"],
                topic_id=topic.id
            )
            session.add(question)
            session.flush()

    session.commit()

    # Seed mock history attempts for progress page
    basic_syntax_topic = session.query(Topic).filter_by(name="Basic Syntax").first()
    functions_topic = session.query(Topic).filter_by(name="Functions").first()
    lists_topic = session.query(Topic).filter_by(name="Lists & Tuples").first()

    # Attempt 1 (Basic Syntax) - Week 1: got 2/3 correct
    questions_syntax = session.query(QuizQuestion).filter_by(topic_id=basic_syntax_topic.id).all()
    for i, q in enumerate(questions_syntax):
        is_correct = (i < 2)
        session.add(QuizAttempt(
            question_id=q.id,
            selected_answer=q.correct_answer if is_correct else ("B" if q.correct_answer != "B" else "A"),
            is_correct=is_correct,
            timestamp=datetime.utcnow() - timedelta(days=14),
            attempt_group_id="mock_attempt_group_1"
        ))

    # Attempt 2 (Basic Syntax Retry) - Week 2: got 3/3 correct
    for q in questions_syntax:
        session.add(QuizAttempt(
            question_id=q.id,
            selected_answer=q.correct_answer,
            is_correct=True,
            timestamp=datetime.utcnow() - timedelta(days=7),
            attempt_group_id="mock_attempt_group_2"
        ))

    # Attempt 3 (Functions) - Week 3: got 3/4 correct
    questions_functions = session.query(QuizQuestion).filter_by(topic_id=functions_topic.id).all()
    for i, q in enumerate(questions_functions):
        is_correct = (i < 3)
        session.add(QuizAttempt(
            question_id=q.id,
            selected_answer=q.correct_answer if is_correct else ("B" if q.correct_answer != "B" else "A"),
            is_correct=is_correct,
            timestamp=datetime.utcnow() - timedelta(days=3),
            attempt_group_id="mock_attempt_group_3"
        ))

    # Attempt 4 (Lists - First try) - Now: got 3/4 correct
    questions_lists = session.query(QuizQuestion).filter_by(topic_id=lists_topic.id).all()
    for i, q in enumerate(questions_lists):
        is_correct = (i < 3)
        session.add(QuizAttempt(
            question_id=q.id,
            selected_answer=q.correct_answer if is_correct else ("B" if q.correct_answer != "B" else "A"),
            is_correct=is_correct,
            timestamp=datetime.utcnow(),
            attempt_group_id="mock_attempt_group_4"
        ))

    session.commit()
    print("Database successfully seeded with starter mock curriculum.")


def main() -> None:
    """
    Main entry point for pipeline script.
    """
    parser = argparse.ArgumentParser(description="YouTube Playlist Adaptive Seeding Pipeline")
    parser.add_argument("playlist_url", nargs="?", help="YouTube playlist URL to parse")
    parser.add_argument("--seed", action="store_true", help="Force database seeding with default mock curriculum")
    parser.add_argument("--limit", type=int, default=5, help="Limit the number of videos processed to avoid rate limits")
    args = parser.parse_args()

    # Determine database URL
    db_url = os.getenv("DATABASE_URL", "sqlite:///adaptive_learning.db")
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # If --seed flag or missing keys, fall back to mock data seeding
    if args.seed or not args.playlist_url:
        if not args.seed:
            print("No playlist URL provided. Seeding database with default curriculum instead.")
        seed_mock_data(session)
        session.close()
        return

    # Check API keys
    gemini_key = os.getenv("GEMINI_API_KEY")

    if not gemini_key:
        print("\n[WARNING] GEMINI_API_KEY is not defined in your environment (.env).")
        print("Falling back to seeding database with default mock curriculum.")
        seed_mock_data(session)
        session.close()
        return

    try:
        raw_videos = fetch_youtube_videos(args.playlist_url)
        if args.limit > 0:
            raw_videos = raw_videos[:args.limit]
            print(f"Limiting parsing to the first {args.limit} videos from the playlist...")
        extracted_metadata = []
        youtube_urls = []

        print("Analyzing videos with Gemini API (this may take a few moments)...")
        for video in raw_videos:
            print(f" -> Analyzing '{video['title']}'...")
            meta = query_gemini_for_metadata(video)
            extracted_metadata.append(meta)
            youtube_urls.append(video['youtube_url'])

        save_to_database(extracted_metadata, youtube_urls, session)
        print("\nPipeline execution completed successfully! The database has been updated.\nSimply refresh your browser tab on http://127.0.0.1:5000 to see your new curriculum!")

    except Exception as e:
        print(f"\n[ERROR] Pipeline run failed: {e}")
        print("Falling back to seeding database with default curriculum...")
        seed_mock_data(session)

    finally:
        session.close()


if __name__ == "__main__":
    main()
