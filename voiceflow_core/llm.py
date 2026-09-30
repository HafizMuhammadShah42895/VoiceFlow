"""LLM integration for text polishing, writing styles, and contextual rewrite."""

import json
import urllib.request
from typing import Callable, Optional

from voiceflow_core.safe_logging import log

DEFAULT_PROMPT = (
    "You are a strict grammar-correction API. You do not answer questions, converse, or add any new information. "
    "Your ONLY job is to fix grammatical and structural errors in the user's text and return the corrected text. "
    "Do NOT wrap the text in quotes, do NOT explain the changes, and do NOT include any preamble. "
    "If the text is already perfect, return it exactly as is."
)
DEFAULT_DICTATION_PROMPT = (
    "Fix the grammar, punctuation, and structure of the dictated text. Remove filler words, repeated words, "
    "stutters, and false starts when they add no meaning. Preserve the speaker's meaning and tone. "
    "Return only the polished text without quotes, explanations, or a preamble."
)
DEFAULT_CONTEXT_PROMPT = (
    "The dictated text is intended as a response or addition to the text in the clipboard. "
    "Rewrite the dictated text to be a polite, professional, and well-formulated response. "
    "DO NOT include the clipboard text in your output."
)
DEFAULT_PRESET_HOTKEY = ["ctrl", "space"]

WRITING_STYLE_PROMPTS = {
    "natural": "Keep the speaker's natural tone and wording.",
    "concise": "Make the result concise and remove redundancy without losing meaning.",
    "professional": "Use a clear, polished, professional tone.",
    "casual": "Use a warm, conversational, casual tone.",
}

GROQ_CHAT_MODEL = "openai/gpt-oss-20b"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_CHAT_MODEL = "llama3"


class LLMService:
    """Manages AI Polish, Smart Replies, and Custom Presets via Groq or Ollama."""

    @staticmethod
    def _chat(
        system_prompt: str,
        user_text: str,
        api_key: str,
        use_local_llm: bool,
        temperature: float,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """Send one chat completion to Ollama or Groq. Returns None on failure."""
        if use_local_llm:
            log("Sending to Local Ollama LLM...")
            try:
                payload = {
                    "model": OLLAMA_CHAT_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text},
                    ],
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                req = urllib.request.Request(
                    OLLAMA_CHAT_URL,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=120) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                log("Local AI response received.")
                return res_data.get("message", {}).get("content", "").strip()
            except Exception as e:
                log(f"Local Ollama API Error: {e}")
                if on_error:
                    on_error("Ollama is offline")
                return None

        if not api_key:
            log("API key missing. Skipping AI request.")
            if on_error:
                on_error("Groq API key missing")
            return None

        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            log("Sending to Groq LLM...")
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                model=GROQ_CHAT_MODEL,
                temperature=temperature,
            )
            log("Groq response received.")
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            log(f"Groq API Error: {e}")
            if on_error:
                on_error("Groq API error")
            return None

    @staticmethod
    def enhance_with_llm(
        text: str,
        prompt: str,
        api_key: str = "",
        use_local_llm: bool = False,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        return LLMService._chat(prompt, text, api_key, use_local_llm, 0.0, on_error)

    @staticmethod
    def apply_post_processing(
        text: str,
        api_key: str,
        is_context_recording: bool = False,
        main_dictation_ai: bool = False,
        writing_style: str = "natural",
        context_prompt: str = DEFAULT_CONTEXT_PROMPT,
        clipboard_context: str = "",
        app_instruction: str = "",
        use_local_llm: bool = False,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Polish dictated text. Falls back to the unpolished text on any failure."""
        if not is_context_recording and not main_dictation_ai:
            return text

        system_prompt = (
            "You are a professional text editor. Your ONLY job is to output the final edited text. "
            "DO NOT add conversational replies, preambles, or quotes."
        )
        user_prompt = f"Here is the dictated text: {text}\n\n"

        if not is_context_recording and main_dictation_ai:
            user_prompt += f"Instruction: {DEFAULT_DICTATION_PROMPT}\n"
            user_prompt += f"Writing style: {WRITING_STYLE_PROMPTS.get(writing_style, WRITING_STYLE_PROMPTS['natural'])}\n"
            if app_instruction.strip():
                user_prompt += f"Application-aware rule: {app_instruction.strip()}\n"

        if is_context_recording and clipboard_context.strip():
            user_prompt += (
                f"Instruction: {context_prompt or DEFAULT_CONTEXT_PROMPT}\n"
                f"[CLIPBOARD START]\n{clipboard_context.strip()}\n[CLIPBOARD END]\n"
            )
            if app_instruction.strip():
                user_prompt += f"Application-aware rule: {app_instruction.strip()}\n"

        edited_text = LLMService._chat(system_prompt, user_prompt, api_key, use_local_llm, 0.3, on_error)
        return edited_text or text
