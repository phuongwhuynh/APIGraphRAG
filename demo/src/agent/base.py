import logging
import json
import os
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Type

from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage

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
    os.makedirs(LOG_DIR, exist_ok=True)

    # Create the logger
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
    def __init__(self, agent_name: str,  model: str, model_provider: str, input_context_window: int, output_context_window: int, **kwarg):
        self.base_llm = init_chat_model(model=model,
                                        model_provider= model_provider,
                                        **kwarg)
        self.input_context_window = input_context_window
        self.output_context_window = output_context_window
        self.messages_logger = setup_file_logger(agent_name + '.messages', LOG_DIR / (agent_name + "_messages.log"))
        self.tokens_logger = setup_file_logger(agent_name + '.tokens', LOG_DIR / (agent_name + "_tokens.log"))
        
    def _context_window_fit(self, contexts: List[List[str]], messages: List[AnyMessage], structured_output: Optional[Type[BaseModel]] = None) -> List[str]:
        token_count = 0

        try:
            # Static prompt template tokens
            token_count += self.base_llm.get_num_tokens_from_messages(messages)
        except:
            # Fall back to a approximation
            self.tokens_logger.error(f"Fail to apply model tokenizer for messages: {[message.content for message in messages]}")
            messages_text = " ".join([message.content for message in messages])
            token_count += self.base_llm.get_num_tokens(messages_text)

        # Structured output tokens
        if structured_output:
            structured_output_dict = structured_output.model_json_schema()
            structured_output_str = json.dumps(structured_output_dict)
            token_count += self.base_llm.get_num_tokens(structured_output_str)

        # The remaining context window size
        left_tokens = self.input_context_window - token_count

        returned_context = []

        for context in contexts:
            result = []
            for c in context:
                token = self.base_llm.get_num_tokens(c)
                left_tokens -= token
                if left_tokens <= 0:
                    break
                result.append(c)
            returned_context.append(result)

        return returned_context



