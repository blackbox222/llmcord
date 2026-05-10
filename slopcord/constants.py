"""Constants for the slopcord bot."""

from discord import Color

# Model tags for vision detection
VISION_MODEL_TAGS = ("claude", "gemini", "gemma", "gpt-4", "gpt-5", "grok-4", "llama", "llava", "mistral", "o3", "o4", "vision", "vl")

# Embed colors
EMBED_COLOR_COMPLETE = Color.dark_green()
EMBED_COLOR_INCOMPLETE = Color.orange()

# Streaming and editing
STREAMING_INDICATOR = " 💬 "
TOOL_INDICATOR = "> 🛠️ "
MAX_MESSAGE_LENGTH = 4096 - len(STREAMING_INDICATOR)
RATE_LIMIT_SECONDS = 1.0

# Message cache limits
MAX_MESSAGE_NODES = 500
MAX_TOKENS = 2048

# Special tokens and LLM finish reasons
EMPTY_THOUGHT = '<|channel>thought\n<channel|>'
GOOD_FINISHES = ("stop", "end_turn", "tool_calls")
