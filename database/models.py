"""
Database models for the Adaptive Python Learning Platform.
Defines SQL database structures and mappings using SQLAlchemy.
"""

from datetime import datetime
import json
from typing import List

from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Topic(Base):
    """
    Topic model to group related videos/subtopics and track overall mastery.
    """
    __tablename__ = 'topics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(Integer, default=1)  # 1: Beginner, 2: Intermediate, 3: Advanced
    mastery_percentage = Column(Float, default=0.0)

    # Relationships
    videos = relationship('Video', back_populates='topic', cascade='all, delete-orphan')
    questions = relationship('QuizQuestion', back_populates='topic', cascade='all, delete-orphan')
    learning_sessions = relationship('LearningSession', back_populates='topic', cascade='all, delete-orphan')

    def __repr__(self) -> str:
        return f"<Topic(id={self.id}, name='{self.name}', mastery={self.mastery_percentage}%)>"


class Video(Base):
    """
    Video model storing YouTube properties and AI metadata extracted from Gemini.
    """
    __tablename__ = 'videos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_name = Column(String(100), nullable=False)
    subtopic = Column(String(100), nullable=False)
    difficulty = Column(Integer, nullable=False)  # 1 | 2 | 3
    depth_level = Column(Integer, nullable=False)  # 1 | 2 | 3
    duration_minutes = Column(Integer, nullable=False)
    prerequisites_json = Column(Text, default='[]')  # Stores JSON list of strings
    order_in_topic = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    youtube_url = Column(String(255), unique=True, nullable=False)

    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=True)
    
    # Relationships
    topic = relationship('Topic', back_populates='videos')
    learning_sessions = relationship('LearningSession', back_populates='video', cascade='all, delete-orphan')

    @property
    def prerequisites(self) -> List[str]:
        """
        Retrieve list of prerequisites from JSON representation.
        
        Returns:
            List[str]: Names of prerequisite topics.
        """
        try:
            return json.loads(self.prerequisites_json) if self.prerequisites_json else []
        except Exception:
            return []

    @prerequisites.setter
    def prerequisites(self, val: List[str]) -> None:
        """
        Store list of prerequisites as JSON.
        
        Args:
            val (List[str]): List of prerequisite topic names.
        """
        self.prerequisites_json = json.dumps(val)

    def __repr__(self) -> str:
        return f"<Video(id={self.id}, subtopic='{self.subtopic}', topic='{self.topic_name}')>"


class QuizQuestion(Base):
    """
    QuizQuestion model representing multiple choice questions stored in database.
    """
    __tablename__ = 'quiz_questions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_text = Column(Text, nullable=False)
    option_a = Column(String(255), nullable=False)
    option_b = Column(String(255), nullable=False)
    option_c = Column(String(255), nullable=False)
    option_d = Column(String(255), nullable=False)
    correct_answer = Column(String(1), nullable=False)  # 'A', 'B', 'C', or 'D'
    difficulty = Column(Integer, nullable=False)  # 1 | 2 | 3
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    video_id = Column(Integer, ForeignKey('videos.id'), nullable=True)  # None = topic-level, set = video-specific

    # Relationships
    topic = relationship('Topic', back_populates='questions')
    attempts = relationship('QuizAttempt', back_populates='question', cascade='all, delete-orphan')

    def __repr__(self) -> str:
        return f"<QuizQuestion(id={self.id}, topic_id={self.topic_id}, video_id={self.video_id}, difficulty={self.difficulty})>"


class QuizAttempt(Base):
    """
    QuizAttempt model recording each question graded answer.
    """
    __tablename__ = 'quiz_attempts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey('quiz_questions.id'), nullable=False)
    selected_answer = Column(String(1), nullable=False)  # 'A', 'B', 'C', or 'D'
    is_correct = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    attempt_group_id = Column(String(100), nullable=False)  # Groups question attempts for a single quiz run

    # Relationships
    question = relationship('QuizQuestion', back_populates='attempts')

    def __repr__(self) -> str:
        return f"<QuizAttempt(id={self.id}, group='{self.attempt_group_id}', is_correct={self.is_correct})>"


class LearningSession(Base):
    """
    LearningSession tracks the video watched and lesson completion state.
    """
    __tablename__ = 'learning_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    video_id = Column(Integer, ForeignKey('videos.id'), nullable=False)
    watched = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationships
    topic = relationship('Topic', back_populates='learning_sessions')
    video = relationship('Video', back_populates='learning_sessions')

    def __repr__(self) -> str:
        return f"<LearningSession(id={self.id}, topic_id={self.topic_id}, watched={self.watched})>"
