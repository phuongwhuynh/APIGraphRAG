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
# LOG_DIR = Path("output/log")

# Define the formatter
formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s \n %(message)s\n\n", 
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Helper function to create dedicated loggers
def setup_file_logger(name: str, log_file: Path, level=logging.INFO) -> logging.Logger:
    """Creates a dedicated logger that writes exclusively to a specific file."""
    # Create the logger
    os.makedirs(log_file.parent, exist_ok=True)

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
    def __init__(self, agent_name: str,  model: str, model_provider: str, input_context_window: int, output_context_window: int, output_dir: str, tokenizer: Optional[str] = None,**kwarg):
        self.base_llm = init_chat_model(model=model,
                                        model_provider= model_provider,
                                        **kwarg)
        self.output_dir = Path(output_dir)

        self.input_context_window = input_context_window
        self.output_context_window = output_context_window
        self.messages_logger = setup_file_logger(agent_name + '.messages', self.output_dir / "log" /  (agent_name + "_messages.log"))
        self.tokens_logger = setup_file_logger(agent_name + '.tokens', self.output_dir  / "log" / (agent_name + "_tokens.log"))

        fallback_tokenizer = "HuggingFaceH4/zephyr-7b-beta"
        try:
            tokenizer_name = tokenizer or fallback_tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
            self.tokens_logger.info(f"Loaded tokenizer successfully: {tokenizer_name}")
        except Exception as e:
            self.tokens_logger.warning(
                f"Unable to load tokenizer '{tokenizer}'. Error: {e}. Falling back to '{fallback_tokenizer}'."
            )
            self.tokenizer = AutoTokenizer.from_pretrained(fallback_tokenizer)
            self.tokens_logger.info(f"Loaded fallback tokenizer successfully: {fallback_tokenizer}")

    def _token_counter(self, messages: AnyMessage | str):
        if not messages: 
            return 0

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
    
    def context_window_fit(self, contexts: str | List[List[str]], messages: List[AnyMessage], structured_output: Optional[Type[BaseModel]]= None) -> str | List[List[str]]:
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

        if isinstance(contexts, str):
            return self._str_context_window_fit(contexts, left_tokens)
        else:
            return self._list_context_window_fit(contexts, left_tokens)

    def _str_context_window_fit(self, contexts: str, left_tokens: int) -> str:
        if left_tokens <= 0:
            return ""
            
        token_ids = self.tokenizer.encode(contexts)
        if len(token_ids) <= left_tokens:
            return contexts
            
        truncated_token_ids = token_ids[:left_tokens]
        return self.tokenizer.decode(truncated_token_ids, skip_special_tokens=True)
        
    def _list_context_window_fit(self, contexts: List[List[str]], left_tokens: int) -> List[List[str]]:
        returned_context = []

        for context in contexts:
            result = []
            for c in context:
                if isinstance(c, str):
                    c = self._str_context_window_fit(c, left_tokens)
                token = self._token_counter(c)
                left_tokens -= token
                if left_tokens <= 0:
                    break
                result.append(c)
            returned_context.append(result)

        return returned_context


    def invoke():
        raise NotImplemented

