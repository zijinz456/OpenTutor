"""Built-in demo course for first-time experience.

Seeds a small 'Python Basics' course with pre-generated content,
flashcards, and quiz questions so users can immediately interact
with the product without uploading any materials.
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.content import CourseContentTree
from models.practice import PracticeProblem
from models.generated_asset import GeneratedAsset
from models.user import User

logger = logging.getLogger(__name__)

DEMO_COURSE_NAME = "Python Basics \u00b7 Quick Start"

# ---------------------------------------------------------------------------
# Content tree: 3 chapters, each with 1-2 sections
# ---------------------------------------------------------------------------
_CONTENT_TREE = [
    {
        "title": "Variables & Data Types",
        "level": 1,
        "order": 0,
        "content": (
            "## Variables in Python\n\n"
            "Python variables are created by assignment \u2014 no type declaration needed.\n\n"
            "```python\nname = \"Alice\"    # str\n"
            "age = 25           # int\n"
            "height = 1.75      # float\n"
            "is_student = True  # bool\n```\n\n"
            "### Common Data Types\n\n"
            "| Type | Example | Mutable |\n"
            "|------|---------|--------|\n"
            "| `int` | `42` | No |\n"
            "| `float` | `3.14` | No |\n"
            "| `str` | `\"hello\"` | No |\n"
            "| `bool` | `True` | No |\n"
            "| `list` | `[1, 2, 3]` | Yes |\n"
            "| `dict` | `{\"a\": 1}` | Yes |\n"
            "| `tuple` | `(1, 2)` | No |\n"
            "| `set` | `{1, 2, 3}` | Yes |\n\n"
            "### Type Conversion\n\n"
            "```python\nint(\"42\")    # str -> int\n"
            "str(42)      # int -> str\n"
            "float(\"3.14\") # str -> float\n```"
        ),
    },
    {
        "title": "Control Flow",
        "level": 1,
        "order": 1,
        "content": (
            "## Conditionals\n\n"
            "```python\nif score >= 90:\n"
            "    grade = \"A\"\n"
            "elif score >= 80:\n"
            "    grade = \"B\"\n"
            "else:\n"
            "    grade = \"C\"\n```\n\n"
            "## Loops\n\n"
            "### for loop\n"
            "```python\nfor i in range(5):\n"
            "    print(i)  # 0, 1, 2, 3, 4\n\n"
            "for name in [\"Alice\", \"Bob\"]:\n"
            "    print(f\"Hello, {name}!\")\n```\n\n"
            "### while loop\n"
            "```python\ncount = 0\n"
            "while count < 3:\n"
            "    print(count)\n"
            "    count += 1\n```\n\n"
            "### Loop Control\n"
            "- `break` \u2014 exit the loop immediately\n"
            "- `continue` \u2014 skip to the next iteration\n"
            "- `pass` \u2014 do nothing (placeholder)"
        ),
    },
    {
        "title": "Functions",
        "level": 1,
        "order": 2,
        "content": (
            "## Defining Functions\n\n"
            "```python\ndef greet(name: str) -> str:\n"
            "    \"\"\"Return a greeting message.\"\"\"\n"
            "    return f\"Hello, {name}!\"\n\n"
            "print(greet(\"Alice\"))  # Hello, Alice!\n```\n\n"
            "## Default & Keyword Arguments\n\n"
            "```python\ndef power(base, exp=2):\n"
            "    return base ** exp\n\n"
            "power(3)        # 9  (uses default exp=2)\n"
            "power(2, 10)    # 1024\n"
            "power(exp=3, base=2)  # 8  (keyword args)\n```\n\n"
            "## Lambda Functions\n\n"
            "```python\nsquare = lambda x: x ** 2\n"
            "print(square(5))  # 25\n\n"
            "# Common with map/filter:\n"
            "nums = [1, 2, 3, 4, 5]\n"
            "evens = list(filter(lambda x: x % 2 == 0, nums))  # [2, 4]\n```\n\n"
            "## Scope\n"
            "- **Local**: defined inside a function\n"
            "- **Global**: defined at module level\n"
            "- Use `global` keyword to modify global vars inside functions"
        ),
    },
]

# ---------------------------------------------------------------------------
# Quiz questions: 8 multiple choice problems
# ---------------------------------------------------------------------------
_QUIZ_QUESTIONS = [
    {
        "question": "Which of the following is a valid Python variable name?",
        "options": {"A": "2name", "B": "_name", "C": "my-name", "D": "class"},
        "correct": "B",
        "explanation": "_name is valid. Variable names can start with a letter or underscore. '2name' starts with a digit, 'my-name' contains a hyphen, and 'class' is a reserved keyword.",
        "knowledge_points": ["variables"],
    },
    {
        "question": "What is the output of `type(3.14)`?",
        "options": {"A": "<class 'int'>", "B": "<class 'float'>", "C": "<class 'str'>", "D": "<class 'decimal'>"},
        "correct": "B",
        "explanation": "3.14 is a floating-point number, so type() returns <class 'float'>.",
        "knowledge_points": ["data_types"],
    },
    {
        "question": "What does `list('abc')` return?",
        "options": {"A": "['abc']", "B": "['a', 'b', 'c']", "C": "[97, 98, 99]", "D": "Error"},
        "correct": "B",
        "explanation": "Passing a string to list() iterates over each character, creating ['a', 'b', 'c'].",
        "knowledge_points": ["data_types", "type_conversion"],
    },
    {
        "question": "What is the output of `range(2, 8, 2)`?",
        "options": {"A": "[2, 4, 6]", "B": "[2, 4, 6, 8]", "C": "[2, 3, 4, 5, 6, 7]", "D": "[2, 8]"},
        "correct": "A",
        "explanation": "range(start, stop, step) generates values from start up to (but not including) stop. So range(2, 8, 2) gives 2, 4, 6.",
        "knowledge_points": ["loops", "range"],
    },
    {
        "question": "Which keyword exits a loop immediately?",
        "options": {"A": "continue", "B": "pass", "C": "break", "D": "return"},
        "correct": "C",
        "explanation": "'break' exits the loop. 'continue' skips to the next iteration. 'pass' does nothing. 'return' exits a function.",
        "knowledge_points": ["loops", "control_flow"],
    },
    {
        "question": "What does `bool('')` evaluate to?",
        "options": {"A": "True", "B": "False", "C": "None", "D": "Error"},
        "correct": "B",
        "explanation": "An empty string is falsy in Python. bool('') returns False. Non-empty strings are truthy.",
        "knowledge_points": ["data_types", "bool"],
    },
    {
        "question": "What is the default value of `exp` in `def power(base, exp=2)`?",
        "options": {"A": "0", "B": "1", "C": "2", "D": "None"},
        "correct": "C",
        "explanation": "The default parameter value is explicitly set to 2 in the function definition.",
        "knowledge_points": ["functions", "default_arguments"],
    },
    {
        "question": "What does `lambda x: x * 2` create?",
        "options": {
            "A": "A class",
            "B": "An anonymous function that doubles its input",
            "C": "A variable named x",
            "D": "A loop",
        },
        "correct": "B",
        "explanation": "lambda creates an anonymous (unnamed) function. This one takes x and returns x * 2.",
        "knowledge_points": ["functions", "lambda"],
    },
]

# ---------------------------------------------------------------------------
# Flashcards: 10 front/back pairs
# ---------------------------------------------------------------------------
_FLASHCARDS = [
    {"front": "How do you declare a variable in Python?", "back": "By direct assignment: `x = 10`. No type declaration needed."},
    {"front": "What is the difference between a list and a tuple?", "back": "Lists are mutable (`[]`), tuples are immutable (`()`). Both are ordered sequences."},
    {"front": "How do you convert a string to an integer?", "back": "`int('42')` returns `42`. Raises ValueError if the string is not a valid integer."},
    {"front": "What does `range(5)` generate?", "back": "The sequence `0, 1, 2, 3, 4`. It starts at 0 and stops before 5."},
    {"front": "What is the difference between `break` and `continue`?", "back": "`break` exits the loop entirely. `continue` skips the rest of the current iteration and moves to the next."},
    {"front": "How do you define a function with a default argument?", "back": "`def greet(name='World'):` \u2014 if no argument is passed, `name` defaults to `'World'`."},
    {"front": "What are Python's falsy values?", "back": "`False`, `0`, `0.0`, `''` (empty string), `[]`, `{}`, `()`, `set()`, `None`."},
    {"front": "What is a lambda function?", "back": "An anonymous, single-expression function: `lambda x: x + 1`. Often used with `map()`, `filter()`, `sorted()`."},
    {"front": "How do you access a dictionary value?", "back": "`d['key']` or `d.get('key', default)`. The `.get()` method avoids KeyError."},
    {"front": "What is a set in Python?", "back": "An unordered collection of unique elements: `{1, 2, 3}`. Supports union, intersection, and difference operations."},
]


async def seed_demo_course(db: AsyncSession) -> bool:
    """Seed the demo course if it does not already exist.

    Returns True if the course was created, False if it already existed.
    """
    # Check if demo course already exists
    result = await db.execute(
        select(Course).where(Course.name == DEMO_COURSE_NAME)
    )
    if result.scalar_one_or_none():
        return False

    # Ensure a local user exists (single-user mode)
    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        user = User(name="Local User")
        db.add(user)
        await db.flush()

    # Create the course
    course = Course(
        name=DEMO_COURSE_NAME,
        description=(
            "A quick-start demo course to experience OpenTutor's core features. "
            "Try chatting with the AI tutor, reviewing flashcards, and taking quizzes!"
        ),
        user_id=user.id,
        active_scene="study_session",
        metadata_={"is_demo": True, "source": "builtin"},
    )
    db.add(course)
    await db.flush()

    # Seed content tree
    for node_data in _CONTENT_TREE:
        node = CourseContentTree(
            course_id=course.id,
            title=node_data["title"],
            content=node_data["content"],
            level=node_data["level"],
            order_index=node_data["order"],
            source_type="manual",
            metadata_={"is_demo": True},
        )
        db.add(node)
    await db.flush()

    # Seed quiz questions
    batch_id = uuid.uuid4()
    for i, q in enumerate(_QUIZ_QUESTIONS):
        problem = PracticeProblem(
            course_id=course.id,
            question_type="mc",
            question=q["question"],
            options=q["options"],
            correct_answer=q["correct"],
            explanation=q["explanation"],
            order_index=i,
            knowledge_points=q["knowledge_points"],
            source="extracted",
            source_batch_id=batch_id,
        )
        db.add(problem)

    # Seed flashcards as a GeneratedAsset batch
    flashcard_batch_id = uuid.uuid4()
    flashcard_asset = GeneratedAsset(
        user_id=user.id,
        course_id=course.id,
        asset_type="flashcard",
        title="Python Basics Flashcards",
        content={"cards": _FLASHCARDS},
        metadata_={"is_demo": True, "card_count": len(_FLASHCARDS)},
        batch_id=flashcard_batch_id,
    )
    db.add(flashcard_asset)

    await db.flush()
    logger.info(
        "Seeded demo course '%s' with %d content nodes, %d quiz questions, %d flashcards",
        DEMO_COURSE_NAME,
        len(_CONTENT_TREE),
        len(_QUIZ_QUESTIONS),
        len(_FLASHCARDS),
    )
    return True
