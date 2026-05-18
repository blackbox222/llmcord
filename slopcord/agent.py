"""Agentic loop implementation"""
from collections import defaultdict, deque
import copy
from datetime import datetime
from enum import StrEnum, auto
import io
import json
import logging
from typing import Any, AsyncGenerator, Callable, Literal

import openai
from openai.types import chat
from pydantic import BaseModel

from . import llm


log = logging.getLogger(__name__)


class EventType(StrEnum):
  UNKNOWN = ''
  START = auto()
  TEXT = auto()
  REASONING = auto()
  STOP = auto()
  TOOL_CALL = auto()
  TOOL_RESULT = auto()


class Event(BaseModel):
  event_type: Literal[EventType.UNKNOWN] = EventType.UNKNOWN
  when: datetime = datetime.now()


class StartEvent(Event):
  event_type: Literal[EventType.START] = EventType.START
  iteration: int = 0


class TextEvent(Event):
  event_type: Literal[EventType.TEXT] = EventType.TEXT
  text: str = ""


class ReasoningEvent(TextEvent):
  event_type: Literal[EventType.REASONING] = EventType.REASONING


class StopEvent(Event):
  event_type: Literal[EventType.STOP] = EventType.STOP
  reason: str = ""
  usage: tuple[int, int] | None = None


class ToolCallEvent(Event):
  event_type: Literal[EventType.TOOL_CALL] = EventType.TOOL_CALL
  id: str = ""
  name: str = ""
  args: dict[str, Any] | None = None


class ToolResultEvent(Event):
  event_type: Literal[EventType.TOOL_RESULT] = EventType.TOOL_RESULT
  id: str = ""
  result: str = ""


class Agent:
  def __init__(self,
               ctx: globals.BotContext,
               client: openai.AsyncOpenAI,
               model_name: str,
               model_params: dict[str, Any],
               system_prompt: str,
               tool_definitions: list[Any]):
    self.ctx = ctx
    self.client = client
    self.model_name = model_name
    self.model_params = model_params
    self.system_prompt = system_prompt
    self.tool_definitions = tool_definitions
    self.tool_impls = {}

    self.messages: list[chat.ChatCompletionMessageParam] = []
    self.max_rounds = 10

  def register_tool(self,
                    tool_name: str,
                    tool_impl: Callable) -> None:
    self.tool_impls[tool_name] = tool_impl


  async def run(self,
                inputs: list[chat.ChatCompletionMessageParam]) -> AsyncGenerator[Event]:
    self.messages.extend(copy.deepcopy(inputs))

    for i in range(self.max_rounds):
      tool_id = ""
      tool_names: defaultdict[str, str] = defaultdict(str)
      tool_args: defaultdict[str, io.StringIO] = defaultdict(io.StringIO)

      full_text = io.StringIO()
      text = io.StringIO()
      reasoning_full_text = io.StringIO()
      reasoning_text = io.StringIO()
      finish_reason = ""
      usage: tuple[int, int] | None = None

      yield StartEvent(iteration=i)

      async for response in llm.generate(
          client=self.client,
          model_name=self.model_name,
          model_params=self.model_params,
          system_prompt=self.system_prompt,
          messages=self.messages,
          tool_defs=self.tool_definitions,
          tool_messages=[]):
        # Accumulate content text/reasoning parts until we run out or hit a newline
        def _consume(content: deque, text: io.StringIO, full_text: io.StringIO):
          while content:
            part = content.popleft()
            head, sep, tail = part.rpartition('\n')
            if head and sep:
              text.write(head)
              text.write(sep)

              yield text.getvalue()

              full_text.write(text.getvalue())
              text = io.StringIO()
              text.write(tail)
            else:
              text.write(part)
        for t in _consume(response.reasoning_content, reasoning_text, reasoning_full_text):
          yield ReasoningEvent(text=t)
        for t in _consume(response.content, text, full_text):
          yield TextEvent(text=t)

        # Accumulate tool calls and arguments
        for id, args in response.tool_calls.items():
          tool_id = id
          if tool_id:
            while args:
              part = args.popleft()
              tool_args[tool_id].write(part)

              if response.tool_names:
                tool_names[tool_id] = response.tool_names[id]

        if response.finish_reason:
          finish_reason = response.finish_reason

        if response.usage:
          usage = response.usage

      # If there is any text left over, yield it and store for the next invocation
      if reasoning_text.tell():
        reasoning_full_text.write(reasoning_text.getvalue())
        yield ReasoningEvent(text=reasoning_text.getvalue())
      if reasoning_full_text.tell():
        self.messages.append(chat.ChatCompletionAssistantMessageParam(role="assistant", content="\n<think>\n" + reasoning_full_text.getvalue() + "\n</think>\n"))

      if text.tell():
        full_text.write(text.getvalue())
        yield TextEvent(text=text.getvalue())
      if full_text.tell():
        self.messages.append(chat.ChatCompletionAssistantMessageParam(role="assistant", content=full_text.getvalue()))

      yield StopEvent(reason=finish_reason, usage=usage)

      # Call tools if there are any, so we can loop again
      if finish_reason == "tool_calls":
        for id, name in tool_names.items():
          args_data = tool_args[id].getvalue()
          args = {}
          if args_data:
            try:
              args = json.loads(tool_args[id].getvalue())
            except Exception as e:
              log.exception(e)

          yield ToolCallEvent(id=id, name=name, args=args or None)

          result = await self.call_tool(id, name, args)
          self.messages.append(chat.ChatCompletionToolMessageParam(role="tool", content=result, tool_call_id=id))

          yield ToolResultEvent(id=id, result=result)

      else:
        break

  async def call_tool(self, id: str, name: str, args: Any) -> str:
    log.info(f"call_tool: id={id}, name={name} args={args!r}")
    try:
      return await self.tool_impls[name](self.ctx, **args)
    except Exception as e:
      log.exception(e)
      return f"ERROR: {e}"

