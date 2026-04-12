import logging
import json
import os
import tiktoken
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Type
from transformers import AutoTokenizer

from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

# Ensure the log directory exists 
LOG_DIR = Path("output/log")

# Define the formatter
formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s \n %(message)s\n\n", 
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Helper function to create dedicated loggers
def setup_file_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Creates a dedicated logger that writes exclusively to a specific file."""
    # Create the logger
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Prevent this logger's messages from bubbling up to the root console logger
    logger.propagate = False 

    # Add the file handler
    if not logger.handlers:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    return logger

class BasicModel():
    """A basic model that offer a context window management for other models"""
    def __init__(self, agent_name: str,  model: str, model_provider: str, input_context_window: int, output_context_window: int, tokenizer: Optional[str] = None,**kwarg):
        self.base_llm = init_chat_model(model=model,
                                        model_provider= model_provider,
                                        **kwarg)

        self.input_context_window = input_context_window
        self.output_context_window = output_context_window
        self.messages_logger = setup_file_logger(agent_name + '.messages', LOG_DIR / (agent_name + "_messages.log"))
        self.tokens_logger = setup_file_logger(agent_name + '.tokens', LOG_DIR / (agent_name + "_tokens.log"))

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer)
        except Exception as e:
            self.tokens_logger.warning(f"Unable to load the tokenizer {tokenizer}. Error: {e}. Fall back to tiktoken")
            self.tokenizer = AutoTokenizer.from_pretrained("HuggingFaceH4/zephyr-7b-beta")

    def _token_counter(self, messages: list[AnyMessage] | str):
        if isinstance(messages, str):
            return len(self.tokenizer.encode(messages))
        
        formated_messages = []
        for message in messages:
            if isinstance(message, SystemMessage):
                formated_messages.append({"role": "system", "content": message.content})
            elif isinstance(message, HumanMessage):
                formated_messages.append({"role": "user", "content": message.content})
            if isinstance(message, AIMessage):
                formated_messages.append({"role": "assistant", "content": message.content})

        token_ids = self.tokenizer.apply_chat_template(
            formated_messages,
            tokenize=True,
            add_generation_prompt=True
        )

        return len(token_ids)
        
    def _context_window_fit(self, contexts: List[List[str]], messages: List[AnyMessage], structured_output: Optional[Type[BaseModel]] = None) -> List[str]:
        token_count = 0

        # Static prompt template tokens
        token_count += self._token_counter(messages)

        # Structured output tokens
        if structured_output:
            structured_output_dict = structured_output.model_json_schema()
            structured_output_str = json.dumps(structured_output_dict)
            token_count += self._token_counter(structured_output_str)

        # The remaining context window size
        left_tokens = self.input_context_window - token_count

        returned_context = []

        for context in contexts:
            result = []
            for c in context:
                token = self._token_counter(c)
                left_tokens -= token
                if left_tokens <= 0:
                    break
                result.append(c)
            returned_context.append(result)

        return returned_context



