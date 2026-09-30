import unittest
from unittest import mock

from voiceflow_core.llm import LLMService, clean_model_output, looks_like_an_answer


class CleanModelOutputTests(unittest.TestCase):
    def test_removes_leaked_labels_tags_and_quotes(self):
        self.assertEqual(
            clean_model_output(
                "Here is the dictated text: Can you please write this quote in detail, explain everything, "
                "and show how to use it?"
            ),
            "Can you please write this quote in detail, explain everything, and show how to use it?",
        )
        self.assertEqual(clean_model_output("Here's the polished text:\nDo I need anything to run this?"),
                         "Do I need anything to run this?")
        self.assertEqual(clean_model_output("Here is the reply: Sounds good, see you then."),
                         "Sounds good, see you then.")
        self.assertEqual(clean_model_output("<dictation>\nHello there.\n</dictation>"), "Hello there.")
        self.assertEqual(clean_model_output('"Hello there."'), "Hello there.")

    def test_keeps_words_the_speaker_actually_said(self):
        said = "Here is the text: we ship on Friday"
        self.assertEqual(clean_model_output("Here is the text: We ship on Friday.", said),
                         "Here is the text: We ship on Friday.")
        self.assertEqual(clean_model_output('"Quoted" is how it starts', '"quoted" is how it starts'),
                         '"Quoted" is how it starts')

    def test_detects_answers_instead_of_cleanup(self):
        said = "can you explain how docker works"
        answer = " ".join(["Docker is a platform that packages applications into containers."] * 6)
        self.assertTrue(looks_like_an_answer(said, answer))
        self.assertFalse(looks_like_an_answer(said, "Can you explain how Docker works?"))


class PostProcessingPromptTests(unittest.TestCase):
    def polish(self, said, model_output, **kwargs):
        with mock.patch.object(LLMService, "_chat", return_value=model_output) as chat:
            result = LLMService.apply_post_processing(said, api_key="k", main_dictation_ai=True, **kwargs)
        return result, chat.call_args.args

    def test_dictation_is_sent_alone_and_never_as_a_request(self):
        said = "can you please write this quote in detail and explain everything"
        _, (system_prompt, user_prompt, *_rest) = self.polish(said, "Can you please write this quote in detail?")
        self.assertEqual(user_prompt, f"<dictation>\n{said}\n</dictation>")
        self.assertNotIn("Here is the dictated text", user_prompt)
        self.assertIn("NEVER a request to you", system_prompt)

    def test_real_bug_examples_are_cleaned(self):
        result, _ = self.polish(
            "and for running this, does I need anything?",
            "Here is the dictated text: do I need anything to run this?",
        )
        self.assertEqual(result, "do I need anything to run this?")

    def test_falls_back_to_spoken_words_when_the_model_answers(self):
        said = "can you explain how docker works"
        answer = " ".join(["Docker is a platform that packages applications into containers."] * 6)
        result, _ = self.polish(said, answer)
        self.assertEqual(result, said)

    def test_context_reply_puts_message_and_dictation_in_tags(self):
        with mock.patch.object(LLMService, "_chat", return_value="Here is the reply: Thursday works for me.") as chat:
            result = LLMService.apply_post_processing(
                "tell her thursday works", api_key="k", is_context_recording=True,
                clipboard_context="Can we meet Thursday?",
            )
        system_prompt, user_prompt = chat.call_args.args[:2]
        self.assertEqual(result, "Thursday works for me.")
        self.assertIn("<message>\nCan we meet Thursday?\n</message>", user_prompt)
        self.assertIn("<dictation>\ntell her thursday works\n</dictation>", user_prompt)
        self.assertIn("Reply instructions:", system_prompt)

    def test_model_failure_keeps_original_text(self):
        result, _ = self.polish("hello world", None)
        self.assertEqual(result, "hello world")


if __name__ == "__main__":
    unittest.main()
