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


def query_gemini_for_all_videos(raw_videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send all video details to Gemini API to classify into topics and generate questions in a single request.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # Prepare minimal input for Gemini to save tokens
    videos_input = []
    for idx, v in enumerate(raw_videos):
        videos_input.append({
            "id": idx,
            "title": v['title'],
            "duration_minutes": v['duration_minutes']
        })

    prompt = f"""
You are a Python curriculum design assistant. You are given a list of videos from a Python programming tutorial playlist.
Your job is to analyze these videos, group them into logical, high-level learning Topics/Modules, and generate quiz questions for each Topic.

Input Videos:
{json.dumps(videos_input, indent=2)}

Your output MUST be a valid JSON object matching this structure EXACTLY:
{{
  "topics": [
    {{
      "name": "Topic Name",
      "description": "Clean developer description of this topic.",
      "difficulty": 1 | 2 | 3,
      "quiz_questions": [
        {{
          "question_text": "Multiple choice question testing a concept in this topic?",
          "option_a": "Choice A",
          "option_b": "Choice B",
          "option_c": "Choice C",
          "option_d": "Choice D",
          "correct_answer": "A" | "B" | "C" | "D",
          "difficulty": 1 | 2 | 3
        }}
      ]
    }}
  ],
  "video_mappings": [
    {{
      "video_id": 0,
      "topic_name": "Topic Name",
      "subtopic": "Specific subtopic of the video",
      "difficulty": 1 | 2 | 3,
      "depth_level": 1 | 2 | 3,
      "order_in_topic": 1
    }}
  ]
}}

Guidelines for fields:
1. `topic_name` / topic `name`: Group all videos into about 6-10 broad, cohesive Python modules (e.g. "Basic Syntax", "Control Flow", "Data Structures", "Functions", "OOP"). Keep topic names consistent across mappings.
2. `difficulty`: 1 (Beginner), 2 (Intermediate), 3 (Advanced).
3. `depth_level`: 1 (Foundational), 2 (Application), 3 (Advanced).
4. `order_in_topic`: 1-based index representing the logical learning order of the video within its topic.
5. Generate exactly 5 multiple choice questions for each topic listed in the `topics` array. Make sure the option keys are correct and correct_answer is one of A, B, C, or D.

Return ONLY the raw JSON string. Do not include any markdown styling, conversational filler, or text outside the JSON object.
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
        # Fallback return structure
        fallback_questions = [
            {
                "question_text": "Which of the following is a key feature of Python programming?",
                "option_a": "Dynamic typing",
                "option_b": "Manual memory management",
                "option_c": "Compilation to machine code only",
                "option_d": "None of the above",
                "correct_answer": "A",
                "difficulty": 1
            }
        ] * 5
        
        fallback_topics = [{
            "name": "General Python",
            "description": "General topics and fundamentals of Python.",
            "difficulty": 1,
            "quiz_questions": fallback_questions
        }]
        
        fallback_mappings = []
        for idx, v in enumerate(raw_videos):
            fallback_mappings.append({
                "video_id": idx,
                "topic_name": "General Python",
                "subtopic": v['title'],
                "difficulty": 1,
                "depth_level": 1,
                "order_in_topic": idx + 1
            })
            
        return {
            "topics": fallback_topics,
            "video_mappings": fallback_mappings
        }


def generate_fallback_curriculum(raw_videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates a structured Python course from video titles using a hybrid
    keyword + index-aware classification strategy.
    """
    topics_definitions = [
        {"name": "Introduction & Setup", "description": "Getting started with Python installation, IDE setup, and basics.", "difficulty": 1},
        {"name": "Variables & Basic Operators", "description": "Working with variables, fundamental data types, and arithmetic/logical operators.", "difficulty": 1},
        {"name": "Control Flow & Decision Making", "description": "Using conditionals (if-else) and loops (for, while) to control execution flow.", "difficulty": 1},
        {"name": "Python Data Structures", "description": "Lists, Tuples, Sets, and Dictionaries in Python.", "difficulty": 2},
        {"name": "Functions & Modular Coding", "description": "Defining functions, arguments, return values, scope, and modules.", "difficulty": 2},
        {"name": "Object-Oriented Programming (OOP)", "description": "Understanding classes, objects, inheritance, polymorphism, and encapsulation.", "difficulty": 3},
        {"name": "File I/O & Exceptions", "description": "Reading and writing files, and handling runtime exceptions safely.", "difficulty": 2},
        {"name": "Advanced Python Concepts", "description": "Decorators, generators, lambda functions, and other advanced utilities.", "difficulty": 3}
    ]

    # --- FIXED: Correct answers verified for every question ---
    topic_questions = {
        "Introduction & Setup": [
            {"question_text": "Who created Python?", "option_a": "Guido van Rossum", "option_b": "James Gosling", "option_c": "Dennis Ritchie", "option_d": "Bjarne Stroustrup", "correct_answer": "A", "difficulty": 1},
            {"question_text": "Which extension is used to save Python files?", "option_a": ".pyt", "option_b": ".pt", "option_c": ".py", "option_d": ".p", "correct_answer": "C", "difficulty": 1},
            {"question_text": "Which of the following is an IDE commonly used for Python?", "option_a": "Eclipse", "option_b": "PyCharm", "option_c": "IntelliJ", "option_d": "Xcode", "correct_answer": "B", "difficulty": 1},
            {"question_text": "Is Python a compiled or interpreted language?", "option_a": "Mainly compiled", "option_b": "Strictly machine binary", "option_c": "None of the above", "option_d": "Mainly interpreted", "correct_answer": "D", "difficulty": 1},
            {"question_text": "How do you display text in Python?", "option_a": "echo()", "option_b": "system.out.println()", "option_c": "printf()", "option_d": "print()", "correct_answer": "D", "difficulty": 1}
        ],
        "Variables & Basic Operators": [
            {"question_text": "Which of the following is a valid variable name in Python?", "option_a": "2myvar", "option_b": "my-var", "option_c": "my_var", "option_d": "my var", "correct_answer": "C", "difficulty": 1},
            {"question_text": "What is the output of print(2 ** 3)?", "option_a": "6", "option_b": "9", "option_c": "5", "option_d": "8", "correct_answer": "D", "difficulty": 1},
            {"question_text": "What type is returned by input() by default?", "option_a": "int", "option_b": "float", "option_c": "str", "option_d": "list", "correct_answer": "C", "difficulty": 1},
            {"question_text": "What does the modulo operator % do?", "option_a": "Performs exponentiation", "option_b": "Returns division remainder", "option_c": "Divides and rounds down", "option_d": "Calculates percentage", "correct_answer": "B", "difficulty": 1},
            {"question_text": "What is the output of print(10 // 3)?", "option_a": "3.333", "option_b": "4", "option_c": "1", "option_d": "3", "correct_answer": "D", "difficulty": 1}
        ],
        "Control Flow & Decision Making": [
            {"question_text": "Which keyword is used for decision-making statement branches in Python?", "option_a": "elseif", "option_b": "else if", "option_c": "switch", "option_d": "elif", "correct_answer": "D", "difficulty": 1},
            {"question_text": "How do you start an infinite loop in Python?", "option_a": "for (;;)", "option_b": "while True:", "option_c": "loop forever", "option_d": "while 1 < 0:", "correct_answer": "B", "difficulty": 1},
            {"question_text": "Which statement terminates the current loop immediately?", "option_a": "continue", "option_b": "pass", "option_c": "break", "option_d": "return", "correct_answer": "C", "difficulty": 1},
            {"question_text": "What is the output of list(range(3))?", "option_a": "1, 2, 3", "option_b": "0, 1, 2, 3", "option_c": "0, 1, 2", "option_d": "1, 2", "correct_answer": "C", "difficulty": 1},
            {"question_text": "Which statement skips the rest of the current loop iteration?", "option_a": "break", "option_b": "continue", "option_c": "pass", "option_d": "exit", "correct_answer": "B", "difficulty": 1}
        ],
        "Python Data Structures": [
            {"question_text": "How do you create an empty list in Python?", "option_a": "list()", "option_b": "[]", "option_c": "Both A and B are correct", "option_d": "{}", "correct_answer": "C", "difficulty": 1},
            {"question_text": "Which collection structure is ordered, indexable, and immutable?", "option_a": "List", "option_b": "Tuple", "option_c": "Set", "option_d": "Dictionary", "correct_answer": "B", "difficulty": 2},
            {"question_text": "Which method adds an item to the end of a list?", "option_a": "add()", "option_b": "insert()", "option_c": "extend()", "option_d": "append()", "correct_answer": "D", "difficulty": 1},
            {"question_text": "Which data structure guarantees unique values?", "option_a": "List", "option_b": "Tuple", "option_c": "Set", "option_d": "Dict", "correct_answer": "C", "difficulty": 2},
            {"question_text": "How do you access the value of key 'name' in dictionary 'd'? (pick most complete answer)", "option_a": "d.name", "option_b": "d['name'] only", "option_c": "d.get('name') only", "option_d": "Both d['name'] and d.get('name')", "correct_answer": "D", "difficulty": 2}
        ],
        "Functions & Modular Coding": [
            {"question_text": "Which keyword is used to declare a function in Python?", "option_a": "func", "option_b": "function", "option_c": "def", "option_d": "lambda", "correct_answer": "C", "difficulty": 1},
            {"question_text": "What is a lambda function?", "option_a": "A function that has no parameters", "option_b": "An anonymous single-line function", "option_c": "A recursive function", "option_d": "A function in math library", "correct_answer": "B", "difficulty": 2},
            {"question_text": "How do you import a module 'math' in Python?", "option_a": "using math", "option_b": "include math", "option_c": "require math", "option_d": "import math", "correct_answer": "D", "difficulty": 1},
            {"question_text": "What does *args represent in a function definition parameter list?", "option_a": "Variable length keyword arguments", "option_b": "Pointer parameters", "option_c": "Variable length positional arguments", "option_d": "Default argument dictionary", "correct_answer": "C", "difficulty": 2},
            {"question_text": "What does **kwargs represent in a function definition parameter list?", "option_a": "Variable length positional arguments", "option_b": "Variable length keyword arguments", "option_c": "Pointer parameters", "option_d": "List arguments", "correct_answer": "B", "difficulty": 2}
        ],
        "Object-Oriented Programming (OOP)": [
            {"question_text": "Which keyword is used to create a class in Python?", "option_a": "def", "option_b": "struct", "option_c": "object", "option_d": "class", "correct_answer": "D", "difficulty": 1},
            {"question_text": "What is the Python constructor method called?", "option_a": "__new__", "option_b": "__init__", "option_c": "construct", "option_d": "class_name", "correct_answer": "B", "difficulty": 2},
            {"question_text": "What represents the current instance of a class in class methods?", "option_a": "this", "option_b": "object", "option_c": "self", "option_d": "inst", "correct_answer": "C", "difficulty": 1},
            {"question_text": "Which concept allows a child class to inherit attributes from a parent class?", "option_a": "Encapsulation", "option_b": "Polymorphism", "option_c": "Abstraction", "option_d": "Inheritance", "correct_answer": "D", "difficulty": 2},
            {"question_text": "How do you call a parent constructor from a child class constructor?", "option_a": "parent.__init__()", "option_b": "this.__init__()", "option_c": "super().__init__()", "option_d": "None of the above", "correct_answer": "C", "difficulty": 2}
        ],
        "File I/O & Exceptions": [
            {"question_text": "Which block is used to catch and handle exceptions in Python?", "option_a": "catch", "option_b": "except", "option_c": "error", "option_d": "finally", "correct_answer": "B", "difficulty": 1},
            {"question_text": "Which built-in function is used to open files in Python?", "option_a": "file()", "option_b": "read()", "option_c": "load()", "option_d": "open()", "correct_answer": "D", "difficulty": 1},
            {"question_text": "Which file mode is used to write to a file, replacing its contents?", "option_a": "'r'", "option_b": "'w'", "option_c": "'a'", "option_d": "'x'", "correct_answer": "B", "difficulty": 1},
            {"question_text": "What is the purpose of the 'finally' block?", "option_a": "Executes clean-up code regardless of exceptions", "option_b": "Executes only if no exceptions occur", "option_c": "Handles specific type of errors", "option_d": "Terminates the program", "correct_answer": "A", "difficulty": 2},
            {"question_text": "What statement raises an exception manually?", "option_a": "throw", "option_b": "except", "option_c": "raise", "option_d": "assert", "correct_answer": "C", "difficulty": 2}
        ],
        "Advanced Python Concepts": [
            {"question_text": "What is a generator in Python?", "option_a": "A script that compiles C programs", "option_b": "A mathematical random function", "option_c": "A function that yields values on demand using 'yield'", "option_d": "An engine that compiles Python to EXE", "correct_answer": "C", "difficulty": 3},
            {"question_text": "What is a decorator in Python?", "option_a": "A function that modifies the behavior of another function", "option_b": "A design pattern tool for UI styling", "option_c": "A tag used for formatting output", "option_d": "A class method constructor", "correct_answer": "A", "difficulty": 3},
            {"question_text": "Which of the following is a list comprehension?", "option_a": "(x for x in range(5))", "option_b": "[x for x in range(5)]", "option_c": "{x for x in range(5)}", "option_d": "list(range(5))", "correct_answer": "B", "difficulty": 2},
            {"question_text": "What does a lambda function return?", "option_a": "None", "option_b": "A list of values", "option_c": "A generator object", "option_d": "The result of its single expression", "correct_answer": "D", "difficulty": 2},
            {"question_text": "Which keyword is used to yield values in a generator?", "option_a": "return", "option_b": "give", "option_c": "yield", "option_d": "output", "correct_answer": "C", "difficulty": 3}
        ]
    }

    # Add quiz questions to the topics definitions
    topics = []
    for topic_def in topics_definitions:
        topic_name = topic_def["name"]
        topics.append({
            "name": topic_name,
            "description": topic_def["description"],
            "difficulty": topic_def["difficulty"],
            "quiz_questions": topic_questions.get(topic_name, [])
        })

    # --- FIXED: Index-aware + keyword hybrid classifier ---
    # Curriculum sequence ranges for the Telusko playlist (101 videos, 0-indexed)
    # These boundaries are heuristic but curriculum-logical:
    #   0-9   → Intro & Setup (first 10: orientation, what is Python)
    #   10-19 → Variables & Basic Operators
    #   20-34 → Control Flow & Decision Making
    #   35-49 → Python Data Structures
    #   50-63 → Functions & Modular Coding
    #   64-74 → OOP
    #   75-84 → File I/O & Exceptions
    #   85+   → Advanced Python Concepts
    INDEX_TOPIC_MAP = [
        (0,   9,  "Introduction & Setup"),
        (10,  19, "Variables & Basic Operators"),
        (20,  34, "Control Flow & Decision Making"),
        (35,  49, "Python Data Structures"),
        (50,  63, "Functions & Modular Coding"),
        (64,  74, "Object-Oriented Programming (OOP)"),
        (75,  84, "File I/O & Exceptions"),
        (85, 999, "Advanced Python Concepts"),
    ]

    DIFFICULTY_BY_TOPIC = {
        "Introduction & Setup": 1,
        "Variables & Basic Operators": 1,
        "Control Flow & Decision Making": 1,
        "Python Data Structures": 2,
        "Functions & Modular Coding": 2,
        "Object-Oriented Programming (OOP)": 3,
        "File I/O & Exceptions": 2,
        "Advanced Python Concepts": 3,
    }

    def classify_video(idx: int, title: str, description: str) -> str:
        """Hybrid: keyword takes priority over index range for specific topics."""
        title_lower = title.lower()
        desc_lower = (description or "").lower()
        combined = title_lower + " " + desc_lower

        # Keyword-priority overrides (specific enough to be reliable)
        if any(w in combined for w in ["abstract class", "inheritance", "polymorphism", "encapsulation", "__init__", "class method", "dunder", "magic method"]):
            return "Object-Oriented Programming (OOP)"
        if any(w in combined for w in ["try:", "except:", "exception", "try except", "file read", "file write", "open(", "with open"]):
            return "File I/O & Exceptions"
        if any(w in combined for w in ["decorator", "generator", "yield", "lambda", "fastapi", "django", "flask", "socket programming", "linear search", "database connection"]):
            return "Advanced Python Concepts"
        if any(w in combined for w in ["dictionary", "dict ", "list comprehension", "tuple", "set in python", "data structure", "zip function"]):
            return "Python Data Structures"
        if any(w in combined for w in ["*args", "**kwargs", "recursion", "scope", "module import", "def ", "function in python"]):
            return "Functions & Modular Coding"

        # Fall through to index-based classification
        for lo, hi, topic_name in INDEX_TOPIC_MAP:
            if lo <= idx <= hi:
                return topic_name
        return "Advanced Python Concepts"

    video_mappings = []
    from collections import defaultdict
    topic_counters: dict = defaultdict(int)

    for idx, v in enumerate(raw_videos):
        topic_name = classify_video(idx, v["title"], v.get("description", ""))
        difficulty = DIFFICULTY_BY_TOPIC.get(topic_name, 1)
        topic_counters[topic_name] += 1

        video_mappings.append({
            "video_id": idx,
            "topic_name": topic_name,
            "subtopic": v["title"].split("|")[0].strip(),
            "difficulty": difficulty,
            "depth_level": difficulty,
            "order_in_topic": topic_counters[topic_name]
        })

    return {
        "topics": topics,
        "video_mappings": video_mappings
    }



def save_to_database(topics: List[Dict[str, Any]], video_mappings: List[Dict[str, Any]], raw_videos: List[Dict[str, Any]], session) -> None:
    """
    Save the batch extracted topics and mapped videos to SQLite.
    """
    print("Saving pipeline results to database...")

    # Clear existing to avoid duplicate conflicts
    session.query(QuizAttempt).delete()
    session.query(LearningSession).delete()
    session.query(QuizQuestion).delete()
    session.query(Video).delete()
    session.query(Topic).delete()
    session.commit()

    topic_cache = {}

    # 1. Create all topics
    for t_data in topics:
        topic_name = t_data.get("name", "General Python")
        if topic_name not in topic_cache:
            topic = Topic(
                name=topic_name,
                description=t_data.get("description") or f"Core concepts about {topic_name}.",
                difficulty=t_data.get("difficulty", 1),
                mastery_percentage=0.0
            )
            session.add(topic)
            session.flush()
            topic_cache[topic_name] = topic

            # Add quiz questions for this topic
            questions = t_data.get("quiz_questions", [])
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

    # Make sure we have a fallback General Python topic if any video mapped to it but it was not created
    if "General Python" not in topic_cache:
        general_topic = Topic(
            name="General Python",
            description="General topics and fundamentals of Python.",
            difficulty=1,
            mastery_percentage=0.0
        )
        session.add(general_topic)
        session.flush()
        topic_cache["General Python"] = general_topic

    # Create mapping of video_id (index in raw_videos) to mapping metadata
    mappings_by_id = {m["video_id"]: m for m in video_mappings}

    # 2. Add all videos
    for idx, raw_v in enumerate(raw_videos):
        mapping = mappings_by_id.get(idx, {})
        topic_name = mapping.get("topic_name", "General Python")
        if topic_name not in topic_cache:
            # Fallback if topic wasn't declared in 'topics' list
            topic = Topic(
                name=topic_name,
                description=f"Core concepts about {topic_name}.",
                difficulty=mapping.get("difficulty", 1),
                mastery_percentage=0.0
            )
            session.add(topic)
            session.flush()
            topic_cache[topic_name] = topic
            
        topic = topic_cache[topic_name]

        video = Video(
            topic_name=topic_name,
            subtopic=mapping.get("subtopic") or raw_v["title"],
            difficulty=mapping.get("difficulty", 1),
            depth_level=mapping.get("depth_level", 1),
            duration_minutes=raw_v["duration_minutes"],
            order_in_topic=mapping.get("order_in_topic", 1),
            description=mapping.get("description") or raw_v["description"][:200],
            youtube_url=raw_v["youtube_url"],
            topic_id=topic.id
        )
        video.prerequisites = mapping.get("prerequisites", [])
        session.add(video)
        session.flush()

        # 3. Create uncompleted LearningSession
        session.add(LearningSession(
            topic_id=topic.id,
            video_id=video.id,
            watched=False,
            timestamp=datetime.utcnow()
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
    parser.add_argument("--limit", type=int, default=150, help="Limit the number of videos processed to avoid rate limits")
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
        
        try:
            print(f"Analyzing all {len(raw_videos)} videos in a single request with Gemini API...")
            result = query_gemini_for_all_videos(raw_videos)
            save_to_database(
                result.get("topics", []),
                result.get("video_mappings", []),
                raw_videos,
                session
            )
            print("\nPipeline execution completed successfully using Gemini API!")
        except Exception as api_err:
            print(f"\n[WARNING] Gemini API failed or rate limited: {api_err}")
            print("Using rule-based local Python curriculum generator as a robust offline fallback to ingest all playlist videos...")
            result = generate_fallback_curriculum(raw_videos)
            save_to_database(
                result.get("topics", []),
                result.get("video_mappings", []),
                raw_videos,
                session
            )
            print("\nPipeline execution completed successfully using offline fallback!")

        print("\nSimply refresh your browser tab on http://127.0.0.1:5000 to see your new curriculum!")

    except Exception as e:
        print(f"\n[ERROR] Pipeline run failed: {e}")
        print("Falling back to seeding database with default curriculum...")
        seed_mock_data(session)

    finally:
        session.close()


if __name__ == "__main__":
    main()
