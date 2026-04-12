import math
import re
from pydantic import BaseModel, Field
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel

class Score(BaseModel):
    score: int = Field(description="")

class GEvalScorer:
    def __init__(self, llm: BaseChatModel, valid_scores: list[int] = [1, 2, 3, 4, 5]):
        """Initializes the G-EVAL scorer.

            Args:
                llm: Any configured LangChain BaseChatModel.
                valid_scores: The numeric scale for evaluation (default 1-5).
        """
        self.llm = llm
        
        # Pre-calculate string versions of valid scores (handling leading spaces)
        self.valid_score_strings = set([str(s) for s in valid_scores] + [f" {s}" for s in valid_scores])
        self.fallback_regex = re.compile(r"Score:\s*([0-9.]+)")

    def evaluate(self, prompt_template_str: str, input_vars: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the G-EVAL prompt and calculates the continuous score."""
        # 1. Build the Universal LangChain Prompt
        prompt = ChatPromptTemplate.from_template(prompt_template_str)
        chain = prompt | self.llm
        
        # 2. Execute the LLM
        response = chain.invoke(input_vars)
        reasoning_text = response.content
        
        # 3. Try Mathematical Extraction (The true G-EVAL method)
        try:
            score = self._extract_logprob_score(response.response_metadata)
            method_used = "Mathematical Expected Value (logprobs)"
        except (KeyError, TypeError, ValueError) as e:
            # 4. Fallback Extraction (If the model doesn't support logprobs)
            print(e)
            score = self._extract_text_score(reasoning_text)
            method_used = "Regex Text Parsing (Fallback)"

        return {
            "score": score,
            "reasoning": reasoning_text,
            "extraction_method": method_used
        }

    def _extract_logprob_score(self, metadata: dict) -> float:
        """Attempts to extract continuous score using OpenAI-style logprobs."""
        # Note: This path specifically targets OpenAI's metadata structure.
        # If using vLLM or TogetherAI, you would map their metadata structure here.
        logprobs_data = metadata["logprobs"]["content"]
        
        # Look at the final token (assuming prompt ends with "Score: ")
        score_token_data = logprobs_data[-1]
        top_candidates = score_token_data.get("top_logprobs", [])

        expected_value = 0.0
        total_probability = 0.0

        for candidate in top_candidates:
            token_text = candidate["token"]
            logprob = candidate["logprob"]
            
            if token_text in self.valid_score_strings:
                probability = math.exp(logprob)
                numeric_value = int(token_text.strip())
                
                expected_value += numeric_value * probability
                total_probability += probability

        if total_probability > 0:
            return round(expected_value / total_probability, 3)
        else:
            print("hihihihi")
            raise ValueError("No valid score tokens found in top logprobs.")

    def _extract_text_score(self, text: str) -> float:
        """Fallback method: Uses regex to find the final score in the text."""
        matches = self.fallback_regex.findall(text)
        if matches:
            return float(matches[-1]) # Get the last occurrence
        
        # Absolute fallback if formatting failed
        return -1.0
    

