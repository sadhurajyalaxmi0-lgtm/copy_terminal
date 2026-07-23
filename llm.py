import os

from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()


import httpx

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    http_client=httpx.Client(verify=False)
)


MODEL = "openai/gpt-4o-mini"



def call_llm(messages, on_chunk=None):

    try:


        if on_chunk is None:
            response = client.chat.completions.create(

                model=MODEL,

                messages=messages,

                temperature=0

            )

            answer = (
                response
                .choices[0]
                .message.content
                .strip()
            )

            usage = response.usage

        else:
            stream = client.chat.completions.create(

                model=MODEL,

                messages=messages,

                temperature=0,

                stream=True,

                stream_options={"include_usage": True}

            )

            answer_parts = []
            usage = None

            for chunk in stream:
                usage = getattr(chunk, "usage", None) or usage

                if not chunk.choices:
                    continue

                content = chunk.choices[0].delta.content

                if content:
                    answer_parts.append(content)
                    on_chunk(content)

            answer = "".join(answer_parts).strip()


        return {

            "answer": answer,

            "input_tokens":
                usage.prompt_tokens if usage else 0,

            "output_tokens":
                usage.completion_tokens if usage else 0,

            "total_tokens":
                usage.total_tokens if usage else 0

        }



    except Exception as error:


        return {

            "answer": f"Error: {error}",

            "input_tokens":0,

            "output_tokens":0,

            "total_tokens":0

        }
