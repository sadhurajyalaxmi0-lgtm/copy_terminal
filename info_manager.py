import json
import re

from rapidfuzz import fuzz


SUMMARY_FIELDS = [
    "name",
    "father_name",
    "age",
    "location",
    "degree",
    "experience",
    "phone_number",
    "favoritecolor",
    "favoritefood",
    "favoritebook",
    "favoritemovie",
    "favoriteplace",
    "favoritesaree",
    "hobbies",
    "skills",
    "workplace",
    "colleaguename",
]


PERSONAL_MAP = {
    "name": "name",
    "father": "father_name",
    "father name": "father_name",
    "age": "age",

    "colleague": "colleaguename",
    "coworker": "colleaguename",

    "color": "favoritecolor",
    "food": "favoritefood",
    "book": "favoritebook",
    "movie": "favoritemovie",
    "place": "favoriteplace",
    "saree": "favoritesaree",

    "hobby": "hobbies",
    "hobbies": "hobbies",

    "skill": "skills",
    "skills": "skills",

    "company": "workplace",
    "office": "workplace",
    "workplace": "workplace",

    "location": "location",
    "city": "location",
    "hometown": "location",

    "degree": "degree",
    "experience": "experience",
    "work experience": "experience",

    "phone": "phone_number",
    "mobile": "phone_number",
}


def normalize(text):
    text = text.lower()
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_info():
    try:
        with open("personal_info.json", "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def save_info(data):
    with open("personal_info.json", "w") as file:
        json.dump(data, file, indent=4)


def detect_personal_info(question):

    question = normalize(question)

    specific_phrases = {
        "colleague name": ["colleague_name"],
        "coworker name": ["colleague_name"],

        # In comparison questions, "name" refers to the requested public
        # figure, while the phrase after "same" identifies the user's data.
        "same location": ["location"],
        "same city": ["location"],
        "same hometown": ["location"],

        "summary of my information": SUMMARY_FIELDS,
        "summary of my personal information": SUMMARY_FIELDS,
        "summarize about me": SUMMARY_FIELDS,
        "summarise about me": SUMMARY_FIELDS,
        "what do you know about me": SUMMARY_FIELDS,
        "tell me about me": SUMMARY_FIELDS,
    }

    for phrase, keys in specific_phrases.items():
        if phrase in question:
            return keys

    detected = []

    for keyword, key in PERSONAL_MAP.items():

        if keyword in question:
            detected.append(key)
            continue

        if fuzz.partial_ratio(keyword, question) >= 90:
            detected.append(key)

    # Preserve question order so combined answers are predictable, while
    # removing duplicate matches such as "hobby" and "hobbies".
    # Keep every explicitly requested "my ..." field, even if it is not in
    # PERSONAL_MAP yet.  This lets callers say which part is unavailable
    # instead of silently omitting it from a multi-field question.
    explicit_fields = re.findall(
        r"\bmy\s+(.+?)(?=\s+and\s+my\s+|$)",
        question,
    )
    for field in explicit_fields:
        field = field.strip()
        if not field:
            continue

        field_words = set(field.split())
        is_known_field = any(
            keyword in field or keyword in field_words
            for keyword in PERSONAL_MAP
        )
        if not is_known_field:
            detected.append(f"unknown::{field}")

    # Preserve question order so combined answers are predictable, while
    # removing duplicate matches such as "hobby" and "hobbies".
    return list(dict.fromkeys(detected))


def format_value(value):

    if isinstance(value, list):
        return ", ".join(value)

    return str(value)


def get_requested_info(keys, session_info=None, prompt_for_missing=True):

    data = load_info()
    result = {}

    session_info = session_info or {}

    for key in keys:

        if key in session_info and session_info[key] not in [None, ""]:
            result[key] = session_info[key]

        elif key in data and data[key] not in [None, ""]:
            result[key] = data[key]

        elif key in {"colleaguename", "colleague_name"}:

            fallback_value = (
                data.get("colleague")
                or data.get("coworker")
            )

            if fallback_value not in [None, ""]:
                data[key] = fallback_value
                result[key] = fallback_value

            elif not prompt_for_missing:
                result[key] = None

            else:
                value = input("\nPlease provide colleague_name: ")
                data[key] = value
                result[key] = value

        else:

            if prompt_for_missing:
                value = input(f"\nPlease provide {key}: ")
                data[key] = value
                result[key] = value
            else:
                result[key] = None

    save_info(data)

    return result


def is_question_about_me(question):

    normalized_question = normalize(question)

    personal_words = {
        "my",
        "mine",
        "me",
        "i",
        "myself",
    }

    personal_phrases = (
        "about me",
        "about myself",
        "tell me about me",
        "what do you know about me",
        "do you know me",
        "my colleague",
        "my coworker",
        "summary of my information",
        "summary of my personal information",
        "summarize about me",
        "summarise about me",
    )

    if any(
        phrase in normalized_question
        for phrase in personal_phrases
    ):
        return True

    words = normalized_question.split()

    return (
        any(word in personal_words for word in words)
        and len(detect_personal_info(question)) > 0
    )


def is_company_information_question(question):

    words = normalize(question).split()

    company_details_words = {
        "headquarters",
        "hq",
        "ceo",
        "founded",
        "revenue",
    }

    if any(word in company_details_words for word in words):
        return True

    company_nouns = {
        "company",
        "workplace",
        "office",
    }

    has_company_noun = any(
        word in company_nouns
        for word in words
    )

    has_location_query = (
        any(
            word in {"located", "location"}
            for word in words
        )
        or "where" in words
    )

    return has_company_noun and has_location_query


def is_comparison_question(question):

    words = normalize(question).split()

    comparison_words = {
        "compare",
        "common",
        "similar",
        "same",
        "difference",
        "between",
        "versus",
        "vs",
    }

    public_entity_words = {
        "celebrity",
        "famous",
        "actor",
        "actress",
        "singer",
        "athlete",
        "politician",
        "leader",
        "political",
        "company",
        "brand",
        "person",
    }

    private_person_words = {
        "colleague",
        "coworker",
        "friend",
        "boss",
        "manager",
        "classmate",
        "family",
        "parent",
        "brother",
        "sister",
    }

    has_user_ref = any(
        word in {"me", "my", "mine", "i", "myself"}
        for word in words
    )

    has_comparison_indicator = (
        any(word in comparison_words for word in words)
        or any(word in public_entity_words for word in words)
        or (
            "who" in words
            and not any(
                word in private_person_words
                for word in words
            )
        )
    )

    return (
        has_user_ref
        and has_comparison_indicator
    )
