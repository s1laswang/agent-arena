"""Gemini parts of Poisoned Inbox (SPEC section 9).

- client.py   GeminiClient (google-genai wrapper) and FakeGemini (scripted, for tests).
- attacker.py Gemini writes new attack wording; fairness + regret filters decide what is kept.
- analyst.py  Gemini groups failed runs into failure types (long context). Offline fallback too.

Gemini never touches the reward. Importing this package never imports google-genai;
the SDK is only loaded when a real Gemini call is made.
"""
