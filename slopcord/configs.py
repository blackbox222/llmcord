"""Configuration management for the slopcord bot."""

import glob
import logging
from typing import Any

import yaml

log = logging.getLogger(__name__)


class Config:
    """Lazy-reloading configuration manager."""

    def __init__(self, filename: str = "config.yaml") -> None:
        self._filename = filename
        self._data: dict[str, Any] = {}
        self._system_prompt_name: str = ""
        self._model_settings: dict[str, float] = {
            "temperature": 1.0,
            "top_p": 0.95,
        }
        self.reload()

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def system_prompt_name(self) -> str:
        return self._system_prompt_name

    @system_prompt_name.setter
    def system_prompt_name(self, value: str) -> None:
        self._system_prompt_name = value

    @property
    def model_settings(self) -> dict[str, float]:
        return self._model_settings

    def reload(self) -> None:
        """Reload configuration from disk."""
        with open(self._filename, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

        # Sync model settings from config
        for key in self._model_settings:
            if key in self._data:
                self._model_settings[key] = float(self._data[key])

        if not self._system_prompt_name:
            self._system_prompt_name = self._data.get("system_prompt_name", "system")

    def get_system_prompt(self, name: str) -> str:
        """Load a system prompt file by name (without extension)."""
        prompt_path = f"prompts/{name}.md"
        if not glob.glob(prompt_path):
            log.warning("Prompt file not found: %s", prompt_path)
            return ""
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()

    def get_prompt_files(self) -> list[str]:
        """Get sorted list of available prompt file names (without extension)."""
        prompt_files = sorted(glob.glob("prompts/*.md"))
        return [f.removeprefix("prompts/").removesuffix(".md") for f in prompt_files]
