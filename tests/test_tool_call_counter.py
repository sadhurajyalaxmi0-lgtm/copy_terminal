import io
import unittest
from unittest.mock import patch

import main
from info_manager import (
    detect_personal_info,
    get_requested_info,
    is_company_information_question,
    is_question_about_me,
)


class ToolCallCounterTests(unittest.TestCase):
    def setUp(self):
        main.messages = [{"role": "system", "content": "system prompt"}]
        main.chat_history = []
        main.summary_batch = []
        main.session_info = {}
        main.tool_call_count = 0
        main.personal_response_cache = {}
        main.tool_usage_counts = {
            "LLM": 0,
            "USER_DATA": 0,
            "CHAT_HISTORY": 0,
        }
        main.llm_calls_this_response = 0
        main.llm_calls_session = 0

    def test_reset_tool_call_count_resets_counter(self):
        main.tool_call_count = 3
        main.reset_tool_call_count()

        self.assertEqual(main.tool_call_count, 0)

    def test_detects_personal_about_me_questions(self):
        self.assertTrue(is_question_about_me("tell me about me"))
        self.assertTrue(is_question_about_me("what do you know about me"))

    def test_does_not_treat_about_me_as_company_question(self):
        self.assertFalse(is_company_information_question("tell me about me"))
        self.assertFalse(is_company_information_question("what do you know about me"))

    def test_get_requested_info_falls_back_to_colleague_alias(self):
        with patch("info_manager.load_info", return_value={"colleague": "Dr. Ada"}), patch(
            "info_manager.save_info"
        ) as mock_save, patch("builtins.input", side_effect=AssertionError("should not prompt")):
            result = get_requested_info(["colleague_name"], session_info={})

        self.assertEqual(result["colleague_name"], "Dr. Ada")
        mock_save.assert_called_once()

    def test_detects_only_colleague_name_for_colleague_questions(self):
        self.assertEqual(detect_personal_info("what is my colleague name"), ["colleague_name"])
        self.assertEqual(detect_personal_info("my coworker name"), ["colleague_name"])

    def test_personal_question_returns_saved_name_and_missing_father_name(self):
        route_result = {
            "answer": "PERSONAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
            "father_name": None,
        }) as mock_info, patch("main.ask_llm", return_value=route_result):
            main.process_question("what is my name and my father's name?")

        mock_info.assert_called_once_with(
            ["name", "father_name"],
            main.session_info,
            prompt_for_missing=False,
        )
        self.assertEqual(
            main.messages[-1]["content"],
            "name: Rajyalaxmi, father's name: I need additional information.",
        )

    def test_multi_field_personal_question_does_not_reuse_stale_cache(self):
        main.personal_response_cache = {
            "what is my name and my father's name": "name: Rajyalaxmi"
        }
        route_result = {
            "answer": "PERSONAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
            "father_name": None,
        }) as mock_info, patch("main.ask_llm", return_value=route_result):
            main.process_question("what is my name and my father's name")

        mock_info.assert_called_once()
        self.assertIn("father's name: I need additional information.", main.messages[-1]["content"])

    def test_personal_question_returns_saved_name_and_missing_experience(self):
        route_result = {
            "answer": "PERSONAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
            "experience": None,
        }), patch("main.ask_llm", return_value=route_result):
            main.process_question("what is my name and my experience")

        self.assertEqual(
            main.messages[-1]["content"],
            "name: Rajyalaxmi, experience: I need additional information.",
        )

    def test_multi_field_question_reports_an_unrecognized_personal_detail(self):
        route_result = {
            "answer": "PERSONAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
            "unknown::date of birth": None,
        }), patch("main.ask_llm", return_value=route_result):
            main.process_question("what is my name and my date of birth")

        self.assertEqual(
            main.messages[-1]["content"],
            "name: Rajyalaxmi, date of birth: I need additional information.",
        )

    def test_about_me_summary_uses_only_saved_personal_information(self):
        route_result = {
            "answer": "GENERAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
            "hobbies": ["reading", "coding"],
            "father_name": None,
        }), patch("main.ask_llm", return_value=route_result):
            main.process_question("what do you know about me?")

        self.assertEqual(
            main.messages[-1]["content"],
            "name: Rajyalaxmi, hobbies: reading, coding",
        )

    def test_summarize_about_me_is_a_personal_profile_request(self):
        route_result = {
            "answer": "GENERAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.get_requested_info", return_value={
            "name": "Rajyalaxmi",
        }), patch("main.ask_llm", return_value=route_result):
            main.process_question("summarize about me?")

        self.assertEqual(main.messages[-1]["content"], "name: Rajyalaxmi")

    def test_comparison_question_returns_no_when_name_missing(self):
        main.messages = [{"role": "system", "content": "system prompt"}]
        main.session_info = {}
        route_result = {
            "answer": "COMPARISON",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }
        with patch("main.load_info", return_value={}), \
             patch("main.ask_llm", return_value=route_result) as mock_ask_llm:

            main.process_question("which celebrity having same name as mine")

            # The assistant's response should be "no"
            self.assertEqual(main.messages[-1]["content"], "no")
            # Only the LLM router is called because the name is missing.
            mock_ask_llm.assert_called_once()
            self.assertEqual(main.tool_call_count, 2)
            self.assertEqual(main.tool_usage_counts["USER_DATA"], 1)
            self.assertEqual(main.tool_usage_counts["LLM"], 1)

    def test_comparison_question_calls_llm_when_name_present(self):
        main.messages = [{"role": "system", "content": "system prompt"}]
        main.session_info = {}
        mock_result = {
            "answer": "Yes, Rajyalaxmi is a well-known actress.",
            "input_tokens": 10,
            "output_tokens": 15,
            "total_tokens": 25
        }
        route_result = {
            "answer": "COMPARISON",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }
        with patch("main.load_info", return_value={"name": "Rajyalaxmi"}), \
             patch("main.ask_llm", side_effect=[route_result, mock_result]) as mock_ask_llm:

            main.process_question("which celebrity having same name as mine")

            # The assistant's response should be from LLM
            self.assertEqual(main.messages[-1]["content"], "Yes, Rajyalaxmi is a well-known actress.")
            # Should have called LLM with injected messages
            self.assertEqual(mock_ask_llm.call_count, 2)
            called_messages = mock_ask_llm.call_args_list[1][0][0]

            # Ensure the injected system message is present in the list passed to LLM
            has_injected = any(
                msg["role"] == "system" and "Rajyalaxmi" in msg["content"]
                for msg in called_messages
            )
            self.assertTrue(has_injected)
            self.assertEqual(main.tool_call_count, 3)
            self.assertEqual(main.tool_usage_counts["USER_DATA"], 1)
            self.assertEqual(main.tool_usage_counts["LLM"], 2)

    def test_celebrity_like_me_uses_saved_hobbies_despite_router_misclassification(self):
        router_result = {
            "answer": "GENERAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }
        answer_result = {
            "answer": "A celebrity who enjoys reading and coding is Mark Zuckerberg.",
            "input_tokens": 5,
            "output_tokens": 4,
            "total_tokens": 9,
        }

        with patch("main.load_info", return_value={"hobbies": ["reading", "coding"]}), \
             patch("main.ask_llm", side_effect=[router_result, answer_result]) as mock_llm:
            main.process_question("which celebrity have hobbies like me?")

        self.assertEqual(main.messages[-1]["content"], answer_result["answer"])
        injected_messages = mock_llm.call_args_list[1][0][0]
        self.assertTrue(any(
            message["role"] == "system" and "User's hobbies: reading, coding" in message["content"]
            for message in injected_messages
        ))

    def test_detects_location_for_location_questions(self):
        self.assertEqual(detect_personal_info("what is my location"), ["location"])
        self.assertEqual(detect_personal_info("which celebrity has the same city as mine"), ["location"])

    def test_location_is_not_treated_as_company_question_without_company_noun(self):
        self.assertFalse(is_company_information_question("what is my location"))
        self.assertTrue(is_company_information_question("where is my company located"))

    def test_repeated_personal_question_uses_cached_response(self):
        main.messages = [{"role": "system", "content": "system prompt"}]
        main.session_info = {}
        route_result = {
            "answer": "PERSONAL",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }
        with patch("main.get_requested_info", return_value={"name": "Rajyalaxmi"}) as mock_info, \
             patch("main.ask_llm", return_value=route_result) as mock_llm:
            main.process_question("what is my name?")
            main.process_question("what is my name?")

        mock_info.assert_called_once_with(
            ["name"],
            main.session_info,
            prompt_for_missing=False,
        )
        self.assertEqual(mock_llm.call_count, 2)
        self.assertEqual(main.tool_call_count, 3)
        self.assertEqual(main.tool_usage_counts["USER_DATA"], 1)
        self.assertEqual(main.tool_usage_counts["CHAT_HISTORY"], 1)
        self.assertEqual(main.tool_usage_counts["LLM"], 2)

    def test_political_leader_comparison_fetches_saved_location(self):
        route_result = {
            "answer": "COMPARISON",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }
        answer_result = {
            "answer": "Asaduddin Owaisi",
            "input_tokens": 5,
            "output_tokens": 3,
            "total_tokens": 8,
        }

        with patch("main.load_info", return_value={"location": "Hyderabad"}), \
             patch("main.ask_llm", side_effect=[route_result, answer_result]) as mock_llm:
            main.process_question(
                "give me any political leader name with same location of mine?"
            )

        injected_messages = mock_llm.call_args_list[1][0][0]
        self.assertTrue(any(
            message["role"] == "system" and "User's location: Hyderabad" in message["content"]
            for message in injected_messages
        ))
        self.assertEqual(main.messages[-1]["content"], "Asaduddin Owaisi")

    def test_general_questions_always_call_the_llm(self):
        main.messages = [{"role": "system", "content": "system prompt"}]
        main.session_info = {}
        result = {
            "answer": "A public answer.",
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
        }
        with patch("main.ask_llm", return_value=result) as mock_llm:
            main.process_question("What is the capital of France?")
            main.process_question("What is the capital of France?")

        self.assertEqual(mock_llm.call_count, 4)
        self.assertEqual(main.tool_call_count, 4)
        self.assertEqual(main.tool_usage_counts["LLM"], 4)

    def test_conversation_summary_increments_llm_usage(self):
        summary_result = {
            "answer": "A concise summary.",
            "input_tokens": 5,
            "output_tokens": 3,
            "total_tokens": 8,
        }
        conversations = [
            {"question": "Question", "answer": "Answer"},
        ]

        with patch("main.call_llm", return_value=summary_result):
            summary = main.summarize_conversation(conversations)

        self.assertEqual(summary, "A concise summary.")
        self.assertEqual(main.tool_call_count, 1)
        self.assertEqual(main.tool_usage_counts["LLM"], 1)
        self.assertEqual(main.llm_calls_this_response, 1)
        self.assertEqual(main.llm_calls_session, 1)

    def test_conversation_summary_passes_all_five_numbered_conversations(self):
        conversations = [
            {"question": f"Question {number}", "answer": f"Answer {number}"}
            for number in range(1, 6)
        ]

        with patch("main.call_llm", return_value={"answer": "Combined summary."}) as mock_llm:
            main.summarize_conversation(conversations)

        summary_prompt = mock_llm.call_args.args[0][1]["content"]
        for number in range(1, 6):
            self.assertIn(f"Conversation {number}:", summary_prompt)
            self.assertIn(f"Question {number}", summary_prompt)
            self.assertIn(f"Answer {number}", summary_prompt)

    def test_llm_calls_increment_for_response_and_session(self):
        result = {
            "answer": "A public answer.",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        }

        with patch("main.ask_llm", return_value=result):
            main.process_question("What is the capital of France?")

        self.assertEqual(main.llm_calls_this_response, 2)
        self.assertEqual(main.llm_calls_session, 2)

        with patch("main.ask_llm", return_value=result):
            main.process_question("What is the capital of Japan?")

        self.assertEqual(main.llm_calls_this_response, 2)
        self.assertEqual(main.llm_calls_session, 4)
