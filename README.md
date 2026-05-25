# PyAdapt — Adaptive Python Learning Platform

PyAdapt is an intelligent, self-paced learning application that generates personalized Python curricula and quiz modules from YouTube playlists. It categorizes lessons dynamically and uses Gemini API to run adaptive pathing, guiding students through levels of core Python programming.

---

## Key Features
- **Dynamic YouTube Pipeline**: Extracts video details, duration, titles, and descriptions, then classifies them via Gemini API into structured topics, difficulties, and depths.
- **Automated Quiz Generation**: Generates contextual multiple-choice questions per video directly during pipeline extraction, varying quiz lengths based on lesson difficulty.
- **Gemini Adaptive Recommendations**: Analyzes the student's full quiz timeline using Gemini (`gemini-1.5-flash`) to make pedagogical path recommendations (advancing or reviewing).
- **Rule-Based Fallback Engine**: Seamlessly falls back to programmatic rules if Gemini API keys are not provided.
- **Analytics Visualization**: Calculates mastery per topic using Pandas, fits linear trend slopes using NumPy `polyfit`, and saves dark-themed performance timelines using Matplotlib.
- **Stunning Dark Theme UI**: A developer-focused, VS-Code/Linear-inspired dark user interface with circuit background nodes and active pulse glow rings.

---

## Project Structure
```
adaptive-learning/
├── app.py                  # Core Flask controller
├── pipeline.py             # CLI YouTube and Gemini parser pipeline
├── requirements.txt        # Pinned dependencies
├── .env                    # Key configuration variables
├── README.md               # Quickstart guide
├── DOCUMENTATION.md        # Technical architecture documentation
├── content/
│   ├── __init__.py
│   └── curriculum.py       # Starter/fallback mock curriculum
├── database/
│   ├── __init__.py
│   └── models.py           # SQLAlchemy SQLite schema models
├── engine/
│   ├── __init__.py
│   ├── adaptive.py         # AI Recommendation engine
│   ├── quiz.py             # Grading and question retriever
│   └── progress.py         # Pandas/NumPy/Matplotlib analytics
├── templates/              # Jinja2 HTML screens
│   ├── dashboard.html
│   ├── lesson.html
│   ├── quiz.html
│   ├── results.html
│   └── progress.html
└── static/
    └── progress_chart.png  # Generated analytics chart
```

---

## Installation & Setup

### 1. Configure Keys
Create a `.env` file in the root directory (based on `.env.example`):
```bash
# Flask Configuration
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=some_secret_key_here

# API Keys
YOUTUBE_API_KEY=your_youtube_v3_api_key
GEMINI_API_KEY=your_gemini_api_key

# Database Settings
DATABASE_URL=sqlite:///adaptive_learning.db
```
*Note: If no API keys are provided in `.env`, the pipeline will automatically fall back to seeding high-quality mock data so you can test the entire platform without credentials.*

### 2. Install Dependencies
Create a virtual environment and install the required libraries:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run Pipeline Seeding
Extract metadata and generate quiz questions:
- **Using a YouTube Playlist (Live AI classification)**:
  ```bash
  python pipeline.py "https://www.youtube.com/playlist?list=PL4Gr5tOAPUM7W-W5VzE9uA2f1N8wY2R6Q"
  ```
- **Using Mock Seeding (Immediate test sandbox)**:
  ```bash
  python pipeline.py --seed
  ```

### 4. Start the Application
Run the Flask server:
```bash
python app.py
```
Open `http://localhost:5000` in your web browser.
