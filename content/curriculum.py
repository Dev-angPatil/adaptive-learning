"""
Starter curriculum content for seeding the database when no API keys are provided
or for initial application state.
"""

from typing import List, Dict, Any

STARTER_CURRICULUM: List[Dict[str, Any]] = [
    {
        "topic": {
            "name": "Basic Syntax",
            "description": "Variables, types, operators, and basic I/O in Python.",
            "difficulty": 1,
            "mastery_percentage": 100.0
        },
        "videos": [
            {
                "subtopic": "Variables and Basic Types",
                "difficulty": 1,
                "depth_level": 1,
                "duration_minutes": 8,
                "prerequisites": [],
                "order_in_topic": 1,
                "description": "An introduction to variables, numbers, strings, and Boolean values in Python.",
                "youtube_url": "https://www.youtube.com/watch?v=khKv-E770ls"
            },
            {
                "subtopic": "Operators and Expressions",
                "difficulty": 1,
                "depth_level": 1,
                "duration_minutes": 10,
                "prerequisites": ["Variables and Basic Types"],
                "order_in_topic": 2,
                "description": "Learn arithmetic, comparison, and logical operators in Python.",
                "youtube_url": "https://www.youtube.com/watch?v=v5MR5JnKcZI"
            }
        ],
        "questions": [
            {
                "question_text": "Which of the following is an invalid variable name in Python?",
                "option_a": "my_variable",
                "option_b": "_variable",
                "option_c": "2my_variable",
                "option_d": "myVariable",
                "correct_answer": "C",
                "difficulty": 1
            },
            {
                "question_text": "What is the output of print(type(1 / 2)) in Python 3?",
                "option_a": "<class 'int'>",
                "option_b": "<class 'float'>",
                "option_c": "<class 'double'>",
                "option_d": "0.5",
                "correct_answer": "B",
                "difficulty": 1
            },
            {
                "question_text": "How do you start a single-line comment in Python?",
                "option_a": "// This is a comment",
                "option_b": "/* This is a comment */",
                "option_c": "# This is a comment",
                "option_d": "<!-- This is a comment -->",
                "correct_answer": "C",
                "difficulty": 1
            }
        ]
    },
    {
        "topic": {
            "name": "Functions",
            "description": "Defining reusable blocks of code using def, return, scope, *args, and **kwargs.",
            "difficulty": 2,
            "mastery_percentage": 100.0
        },
        "videos": [
            {
                "subtopic": "Defining Functions and Scope",
                "difficulty": 2,
                "depth_level": 1,
                "duration_minutes": 12,
                "prerequisites": ["Basic Syntax"],
                "order_in_topic": 1,
                "description": "Learn to declare functions using def, handle return statements, and understand local vs global scope.",
                "youtube_url": "https://www.youtube.com/watch?v=9Os0o3wzS_I"
            },
            {
                "subtopic": "Arguments: *args and **kwargs",
                "difficulty": 2,
                "depth_level": 2,
                "duration_minutes": 15,
                "prerequisites": ["Defining Functions and Scope"],
                "order_in_topic": 2,
                "description": "Master flexible argument passing in Python using positional arguments (*args) and keyword arguments (**kwargs).",
                "youtube_url": "https://www.youtube.com/watch?v=4a777y15tDY"
            }
        ],
        "questions": [
            {
                "question_text": "What is the primary purpose of *args in a function definition?",
                "option_a": "To allow the function to accept any number of keyword arguments.",
                "option_b": "To enforce type checking on positional arguments.",
                "option_c": "To allow the function to accept any number of positional arguments.",
                "option_d": "To return multiple values from the function.",
                "correct_answer": "C",
                "difficulty": 2
            },
            {
                "question_text": "Which keyword is used to access or modify a global variable inside a local function scope?",
                "option_a": "global",
                "option_b": "nonlocal",
                "option_c": "outer",
                "option_d": "public",
                "correct_answer": "A",
                "difficulty": 2
            },
            {
                "question_text": "What does a function return in Python if it does not contain a return statement?",
                "option_a": "0",
                "option_b": "None",
                "option_c": "False",
                "option_d": "An empty string",
                "correct_answer": "B",
                "difficulty": 2
            },
            {
                "question_text": "In a function signature definition, what type of collection is kwargs passed as?",
                "option_a": "Tuple",
                "option_b": "List",
                "option_c": "Dictionary",
                "option_d": "Set",
                "correct_answer": "C",
                "difficulty": 2
            }
        ]
    },
    {
        "topic": {
            "name": "Lists & Tuples",
            "description": "Indexing, slicing, and list comprehensions for list manipulation.",
            "difficulty": 2,
            "mastery_percentage": 60.0
        },
        "videos": [
            {
                "subtopic": "List Operations and Slicing",
                "difficulty": 2,
                "depth_level": 1,
                "duration_minutes": 10,
                "prerequisites": ["Basic Syntax"],
                "order_in_topic": 1,
                "description": "Understanding indexing, sub-lists, steps, and list operations.",
                "youtube_url": "https://www.youtube.com/watch?v=9OeznAkyQz4"
            },
            {
                "subtopic": "List Comprehensions",
                "difficulty": 2,
                "depth_level": 2,
                "duration_minutes": 14,
                "prerequisites": ["List Operations and Slicing", "Defining Functions and Scope"],
                "order_in_topic": 2,
                "description": "Learn the elegant, concise syntax for creating lists from existing collections or iterables.",
                "youtube_url": "https://www.youtube.com/watch?v=3dt4OGnU5sM"
            }
        ],
        "questions": [
            {
                "question_text": "Which of the following is the correct syntax for a list comprehension that squares all even numbers in a list nums?",
                "option_a": "[x^2 for x in nums if x % 2 == 0]",
                "option_b": "[x**2 for x in nums if x % 2 == 0]",
                "option_c": "[for x in nums x**2 if x % 2 == 0]",
                "option_d": "[x**2 if x % 2 == 0 for x in nums]",
                "correct_answer": "B",
                "difficulty": 2
            },
            {
                "question_text": "What is the value of nums[-2] for nums = [10, 20, 30, 40, 50]?",
                "option_a": "10",
                "option_b": "20",
                "option_c": "40",
                "option_d": "50",
                "correct_answer": "C",
                "difficulty": 2
            },
            {
                "question_text": "What is the difference between a list and a tuple in Python?",
                "option_a": "Lists are immutable; tuples are mutable.",
                "option_b": "Lists are mutable; tuples are immutable.",
                "option_c": "Lists can only hold strings; tuples can hold any type.",
                "option_d": "There is no difference.",
                "correct_answer": "B",
                "difficulty": 2
            },
            {
                "question_text": "What is the result of [1, 2] * 3 in Python?",
                "option_a": "[3, 6]",
                "option_b": "[1, 2, 1, 2, 1, 2]",
                "option_c": "[[1, 2], [1, 2], [1, 2]]",
                "option_d": "An error is raised.",
                "correct_answer": "B",
                "difficulty": 2
            }
        ]
    },
    {
        "topic": {
            "name": "Classes (OOP)",
            "description": "Objects, instance variables, methods, inheritance, and polymorphism.",
            "difficulty": 3,
            "mastery_percentage": 0.0
        },
        "videos": [
            {
                "subtopic": "Classes and Object Instances",
                "difficulty": 3,
                "depth_level": 1,
                "duration_minutes": 15,
                "prerequisites": ["Functions"],
                "order_in_topic": 1,
                "description": "Understand how to model real-world concepts using classes, objects, and constructor methods (__init__).",
                "youtube_url": "https://www.youtube.com/watch?v=apACNr7DC_s"
            },
            {
                "subtopic": "Inheritance and Polymorphism",
                "difficulty": 3,
                "depth_level": 2,
                "duration_minutes": 18,
                "prerequisites": ["Classes and Object Instances"],
                "order_in_topic": 2,
                "description": "Learn to extend classes using inheritance and write polymorphic functions to handle child classes.",
                "youtube_url": "https://www.youtube.com/watch?v=RSl87lqOXDE"
            }
        ],
        "questions": [
            {
                "question_text": "Which method is the constructor in Python classes?",
                "option_a": "__new__",
                "option_b": "__init__",
                "option_c": "__create__",
                "option_d": "constructor",
                "correct_answer": "B",
                "difficulty": 3
            },
            {
                "question_text": "What does the 'self' parameter refer to inside a class method?",
                "option_a": "The parent class.",
                "option_b": "The method itself.",
                "option_c": "The specific instance of the object being created or modified.",
                "option_d": "The global program namespace.",
                "correct_answer": "C",
                "difficulty": 3
            },
            {
                "question_text": "How do you call a method in the parent class from a subclass in Python?",
                "option_a": "parent().method()",
                "option_b": "super().method()",
                "option_c": "this.parent().method()",
                "option_d": "base.method()",
                "correct_answer": "B",
                "difficulty": 3
            },
            {
                "question_text": "Which of the following is true about polymorphism in Python?",
                "option_a": "It requires defining multiple functions with the same name and different signatures.",
                "option_b": "It allows different classes to have methods with the same name, behaving differently based on the object's type.",
                "option_c": "Python does not support polymorphism.",
                "option_d": "It requires compiler-level type casting.",
                "correct_answer": "B",
                "difficulty": 3
            },
            {
                "question_text": "What is the double underscore prefix and suffix pattern (e.g. __str__) called in Python OOP?",
                "option_a": "Magic or dunder methods.",
                "option_b": "Private methods.",
                "option_c": "Internal methods.",
                "option_d": "System functions.",
                "correct_answer": "A",
                "difficulty": 3
            }
        ]
    }
]
