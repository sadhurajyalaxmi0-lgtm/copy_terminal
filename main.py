import threading
import time
import re
from datetime import datetime

from colorama import Fore, Style, init

from prompts import SYSTEM_PROMPT
from llm import call_llm
from memory import compress_messages

from info_manager import (
    detect_personal_info,
    get_requested_info,
    is_question_about_me,
    is_comparison_question,
    is_company_information_question,
    load_info,
)

init(autoreset=True)

messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]

chat_history = []
summary_batch = []
session_info = {}
personal_response_cache = {}
tool_call_count = 0
current_question_tool_calls = []
tool_usage_counts = {
    "LLM": 0,
    "USER_DATA": 0,
    "CHAT_HISTORY": 0,
}
llm_calls_this_response = 0
llm_calls_session = 0
LLM_TOOL_NAMES = {
    "get_question_route",
    "get_general_data_tool",
    "summarize_conversation",
}
current_query_route = ""
STREAM_CHARACTER_DELAY = 0.02


def track_tool_call(tool_name):
    global tool_call_count, current_question_tool_calls, tool_usage_counts
    global llm_calls_this_response, llm_calls_session

    tool_call_count += 1
    current_question_tool_calls.append((tool_call_count, tool_name))

    if tool_name == "get_personal_data_tool":
        tool_usage_counts["USER_DATA"] += 1
    elif tool_name in LLM_TOOL_NAMES:
        tool_usage_counts["LLM"] += 1
        llm_calls_this_response += 1
        llm_calls_session += 1


def reset_tool_call_count():
    global tool_call_count, current_question_tool_calls, tool_usage_counts
    global llm_calls_this_response, llm_calls_session

    tool_call_count = 0
    current_question_tool_calls = []
    tool_usage_counts = {
        "LLM": 0,
        "USER_DATA": 0,
        "CHAT_HISTORY": 0,
    }
    llm_calls_this_response = 0
    llm_calls_session = 0


def track_history_use():
    """Record a response reused from the personal-answer cache."""

    tool_usage_counts["CHAT_HISTORY"] += 1


def print_tool_call_summary():
    """Print the route and tool usage for the current response."""

    current_user_data_calls = sum(
        tool_name == "get_personal_data_tool"
        for _, tool_name in current_question_tool_calls
    )
    current_history_calls = int("CHAT_HISTORY" in current_query_route)

    print(
        Fore.BLUE +
        f"\nActive route: {current_query_route}" +
        Style.RESET_ALL
    )
    print(
        Fore.MAGENTA +
        "Calls (this response): "
        f"LLM={llm_calls_this_response} | "
        f"USER_DATA={current_user_data_calls} | "
        f"CHAT_HISTORY={current_history_calls}" +
        Style.RESET_ALL
    )
    print(
        Fore.MAGENTA +
        "Calls (session): "
        f"LLM={llm_calls_session} | "
        f"USER_DATA={tool_usage_counts['USER_DATA']} | "
        f"CHAT_HISTORY={tool_usage_counts['CHAT_HISTORY']}" +
        Style.RESET_ALL
    )


def loading_animation(stop_event):
    dots = ""

    while not stop_event.is_set():
        dots += "."

        if len(dots) > 3:
            dots = ""

        print(
            "\r" + Fore.CYAN +
            "Assistant is typing" +
            dots,
            end="",
            flush=True
        )

        time.sleep(0.5)

    print("\r" + " " * 50, end="\r")


def ask_llm(custom_messages=None, stream_response=True):
    stop_event = threading.Event()
    stream_started = threading.Event()

    loader = threading.Thread(
        target=loading_animation,
        args=(stop_event,)
    )

    loader.start()

    def print_chunk(chunk):
        if not stream_started.is_set():
            stop_event.set()
            loader.join()

            print(
                Fore.CYAN +
                "\nAssistant: " +
                Fore.YELLOW,
                end="",
                flush=True
            )

            stream_started.set()

        for character in chunk:
            print(character, end="", flush=True)
            time.sleep(STREAM_CHARACTER_DELAY)

    msgs = custom_messages if custom_messages is not None else messages
    result = call_llm(
        msgs,
        on_chunk=print_chunk if stream_response else None
    )

    stop_event.set()
    loader.join()

    if stream_started.is_set():
        print(Style.RESET_ALL)
        result["streamed"] = True

    return result


def get_personal_data_tool(keys, include_missing=True):
    """Return personal information from memory and storage."""

    # A question may request several facts at once.  Return saved facts and
    # clearly mark any unavailable private detail instead of prompting for it
    # or allowing the model to invent it.
    info = get_requested_info(
        keys,
        session_info,
        prompt_for_missing=False,
    )

    values = []

    for key, value in info.items():

        if key.startswith("unknown::"):
            label = key.removeprefix("unknown::")
        elif key == "father_name":
            label = "father's name"
        else:
            label = key

        if value is None and not include_missing:
            continue

        if value is None:
            values.append(f"{label}: I need additional information.")
            continue

        if isinstance(value, list):
            value = ", ".join(value)

        values.append(
            f"{label}: {value}"
        )

    track_tool_call("get_personal_data_tool")

    return ", ".join(values)


def get_general_data_tool(custom_messages=None):
    """Return a general/public answer using the configured LLM knowledge."""

    result = ask_llm(custom_messages)

    track_tool_call("get_general_data_tool")

    return result


def get_question_route(question):
    """Use the LLM to determine how a question should be handled."""

    routing_messages = [
        {
            "role": "system",
            "content": (
                "Classify the user's question into exactly one route. "
                "Reply with only one label: PERSONAL, COMPARISON, "
                "DATE_TIME, or GENERAL. PERSONAL asks about the user's "
                "saved information. COMPARISON compares the user with a "
                "public figure. DATE_TIME asks for the current date or time."
            ),
        },
        {
            "role": "user",
            "content": question,
        },
    ]

    result = ask_llm(routing_messages, stream_response=False)
    route_match = re.search(
        r"\b(PERSONAL|COMPARISON|DATE_TIME|GENERAL)\b",
        result["answer"].upper(),
    )

    # The user explicitly compares themself with a public figure here.  This
    # deterministic check takes precedence over a router misclassification
    # such as PERSONAL or GENERAL for wording like "celebrity like me".
    if is_comparison_question(question):
        route = "COMPARISON"
    elif (
        is_question_about_me(question)
        and not is_company_information_question(question)
    ):
        # Stored-profile requests must not be routed to the general model,
        # even when the LLM router labels them GENERAL.
        route = "PERSONAL"
    elif route_match:
        route = route_match.group(1)
    elif is_date_time_question(question):
        route = "DATE_TIME"
    else:
        route = "GENERAL"

    track_tool_call("get_question_route")

    return route, result


def get_response_details(result):
    """Extract a response and its token counts from an LLM result."""

    return (
        result["answer"],
        result["input_tokens"],
        result["output_tokens"],
        result["total_tokens"],
    )


def is_date_time_question(question):
    """Identify questions that request the current local date or time."""

    normalized_question = question.lower()
    date_time_phrases = (
        "current time",
        "time now",
        "what time",
        "current date",
        "date today",
        "today's date",
        "what date",
        "date and time",
        "time and date",
        "what day is it"
    )

    return any(
        phrase in normalized_question
        for phrase in date_time_phrases
    )


def get_date_time_tool():
    """Return the computer's current local date and time."""

    current_date_time = datetime.now()

    result = current_date_time.strftime(
        "Current date and time: %A, %d %B %Y, %I:%M:%S %p"
    )

    track_tool_call("get_date_time_tool")

    return result


def summarize_conversation(conversations):
    """Create one combined summary that covers every exchange in a batch."""

    numbered_conversations = []
    for number, conversation in enumerate(conversations, start=1):
        numbered_conversations.append(
            f"Conversation {number}:\n"
            f"User: {conversation['question']}\n"
            f"Assistant: {conversation['answer']}"
        )

    summary_messages = [
        {
            "role": "system",
            "content": (
                "Write one concise combined summary of conversations 1 through 5. "
                "Cover the key topic or outcome from every numbered conversation; "
                "do not summarize only the final conversation. Use 2 to 4 sentences "
                "when possible. Do not add a heading."
            )
        },
        {
            "role": "user",
            "content": "\n\n".join(numbered_conversations)
        }
    ]

    result = call_llm(summary_messages)
    track_tool_call("summarize_conversation")

    return result["answer"]


def process_question(question):

    global messages, chat_history, summary_batch, session_info
    global personal_response_cache, current_question_tool_calls
    global current_query_route
    global llm_calls_this_response

    current_question_tool_calls = []
    llm_calls_this_response = 0

    messages.append({
        "role": "user",
        "content": question
    })

    name_match = re.search(
        r"my name is\s+([a-zA-Z]+)",
        question.lower()
    )

    if name_match:
        session_info["name"] = name_match.group(1).title()

    response = ""
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    streamed = False

    question_route, route_result = get_question_route(question)
    input_tokens += route_result["input_tokens"]
    output_tokens += route_result["output_tokens"]
    total_tokens += route_result["total_tokens"]


    # Comparison questions
    if question_route == "COMPARISON":
        current_query_route = "LLM_ROUTER + USER_DATA"

        keys = detect_personal_info(question)
        info_data = load_info()
        has_required_info = True
        personal_context = {}

        for key in keys:
            val = session_info.get(key) or info_data.get(key)
            if not val and key == "colleague_name":
                val = info_data.get("colleague") or info_data.get("coworker")

            if val not in [None, ""]:
                personal_context[key] = val
            else:
                has_required_info = False
                break

        track_tool_call("get_personal_data_tool")

        if keys and not has_required_info:
            response = "no"
        else:
            current_query_route = "LLM_ROUTER + USER_DATA + LLM"
            custom_messages = list(messages)
            if personal_context:
                context_lines = []
                for k, v in personal_context.items():
                    if isinstance(v, list):
                        v = ", ".join(v)
                    context_lines.append(f"User's {k}: {v}")
                context_str = "\n".join(context_lines)
                extra_instruction = (
                    "This is a comparison between the user and a public figure, such as a "
                    "celebrity, politician, or political leader. The personal information "
                    "above is complete and authoritative for this request. Never ask for "
                    "additional information and never reply with 'I need additional information'. "
                    "When the user asks which celebrity is like them, name a celebrity whose "
                    "publicly known interests match the supplied user information. "
                    "For a same-location request, use the supplied location to name a public "
                    "figure associated with that exact location. If no reliable match is found, "
                    "reply exactly: 'no'."
                )
                custom_messages.insert(1, {
                    "role": "system",
                    "content": f"Here is the user's personal information:\n{context_str}\n{extra_instruction}"
                })

            result = get_general_data_tool(custom_messages)

            (
                response,
                answer_input_tokens,
                answer_output_tokens,
                answer_total_tokens,
            ) = get_response_details(result)
            input_tokens += answer_input_tokens
            output_tokens += answer_output_tokens
            total_tokens += answer_total_tokens
            streamed = result.get("streamed", False)


    # Date and time questions
    elif question_route == "DATE_TIME":
        current_query_route = "LLM_ROUTER + DATE_TIME"

        response = get_date_time_tool()

    # Personal questions
    elif question_route == "PERSONAL":
        cache_key = question.strip().casefold()
        requested_keys = detect_personal_info(question)
        normalized_question = question.casefold()
        is_profile_summary = any(
            phrase in normalized_question
            for phrase in (
                "what do you know about me",
                "tell me about me",
                "summary of my information",
                "summary of my personal information",
                "summarize about me",
                "summarise about me",
            )
        )

        # Only single-field lookups are safe to reuse.  A multi-field request
        # can have an older partial response in the cache (for example, a
        # saved name without the requested father's name).
        if cache_key in personal_response_cache and len(requested_keys) == 1:
            current_query_route = "LLM_ROUTER + CHAT_HISTORY"
            track_history_use()
            response = personal_response_cache[cache_key]
        else:
            current_query_route = "LLM_ROUTER + USER_DATA"
            response = get_personal_data_tool(
                requested_keys,
                include_missing=not is_profile_summary,
            )
            personal_response_cache[cache_key] = response

    # General / Public questions
    else:
        current_query_route = "LLM_ROUTER + LLM"

        result = get_general_data_tool()

        (
            response,
            answer_input_tokens,
            answer_output_tokens,
            answer_total_tokens,
        ) = get_response_details(result)
        input_tokens += answer_input_tokens
        output_tokens += answer_output_tokens
        total_tokens += answer_total_tokens
        streamed = result.get("streamed", False)

    response = str(response)

    messages.append({
        "role": "assistant",
        "content": response
    })

    messages = compress_messages(messages)

    chat_history.append({
        "question": question,
        "answer": response
    })

    chat_history = chat_history[-4:]

    summary_batch.append({
        "question": question,
        "answer": response
    })


    if not streamed:
        print(
            Fore.CYAN +
            "\nAssistant: " +
            Fore.YELLOW +
            response +
            Style.RESET_ALL
        )


    if len(summary_batch) == 5:

        summary = summarize_conversation(summary_batch)

        print(
            Fore.BLUE +
            "\nConversation summary (chats 1-5): " +
            Fore.YELLOW +
            summary
        )

        summary_batch = []


    if total_tokens > 0:

        print(
            Fore.MAGENTA +
            f"\nInput tokens : {input_tokens}"
        )

        print(
            Fore.MAGENTA +
            f"Output tokens: {output_tokens}"
        )

        print(
            Fore.MAGENTA +
            f"Total tokens : {total_tokens}"
        )

    print_tool_call_summary()

def run_chat_loop():

    global messages, chat_history, summary_batch, session_info, personal_response_cache

    while True:

        question = input(
            Fore.GREEN +
            "\nYou: " +
            Style.RESET_ALL
        ).strip()


        if question.lower() in [
            "exit",
            "quit",
            "stop"
        ]:

            print(
                Fore.MAGENTA +
                "\nGoodbye!"
            )

            break


        if question.lower() == "clear":

            messages = [messages[0]]
            chat_history = []
            summary_batch = []
            session_info = {}
            personal_response_cache = {}
            reset_tool_call_count()

            print(
                Fore.RED +
                "\nChat history cleared."
            )

            continue


        if question.lower() == "history":

            print(
                Fore.BLUE +
                "\nLast conversations:\n"
            )

            if not chat_history:

                print(
                    Fore.RED +
                    "No history found."
                )

            else:

                for i, chat in enumerate(
                    chat_history,
                    start=1
                ):

                    print(
                        Fore.GREEN +
                        f"{i}. You: {chat['question']}"
                    )

                    print(
                        Fore.YELLOW +
                        f"Assistant: {chat['answer']}\n"
                    )

            continue


        if question:
            process_question(question)


if __name__ == "__main__":
    run_chat_loop()

