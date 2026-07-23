import json
import os


HISTORY_FILE = "chat_history.json"


def load_history():

    if not os.path.exists(

        HISTORY_FILE

    ):

        return []

    with open(

        HISTORY_FILE,
        "r"

    ) as file:

        return json.load(

            file

        )


def save_history(history):

    with open(

        HISTORY_FILE,
        "w"

    ) as file:

        json.dump(

            history,
            file,
            indent=2

        )


def add_to_history(

    question,
    answer

):

    history = load_history()

    history.append(

        {
            "question": question,
            "answer": answer
        }

    )

    history = history[-3:]

    save_history(

        history

    )