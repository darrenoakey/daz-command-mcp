#!/usr/bin/env python3
"""
LLM Summary Generator - Core logic for generating repository architecture summaries.

This module contains the pure summary generation logic, separated from worker management.
It focuses on prompt creation, LLM interaction, and result processing.
"""

from __future__ import annotations

import json
import sys
import time
import re
from typing import Any, Dict, List, Optional

# Fail-fast dependency check
try:
    from dazllm import Llm
except ImportError as e:
    print(f"FATAL ERROR: dazllm module not available: {e}", file=sys.stderr)
    print(f"Install with: {sys.executable} -m pip install dazllm", file=sys.stderr)
    print(f"Current Python executable: {sys.executable}", file=sys.stderr)
    sys.exit(1)

from .models import LLM_MODEL_NAME, Event
from .utils import truncate_with_indication


class SummaryGenerator:
    """Handles LLM-based summary generation for repository architecture documents."""
    
    def __init__(self, model_name: str = LLM_MODEL_NAME):
        """Initialize the summary generator with the specified model."""
        self.model_name = model_name
        self._llm = None
        self._initialized = False
        self._init_error = None
    
    def initialize(self) -> bool:
        """
        Initialize the LLM connection and test it.
        
        Returns:
            True if initialization succeeded, False otherwise.
            
        Raises:
            RuntimeError: If initialization fails with detailed error info.
        """
        try:
            self._llm = Llm.model_named(self.model_name)
            if self._llm is None:
                self._init_error = f"LLM initialization failed - model '{self.model_name}' not available"
                self._initialized = False
                return False
            
            # Test the LLM with a simple query to ensure it's working
            test_response = self._llm.chat("Hello, please respond with 'OK' if you are working.")
            
            if test_response is None or len(test_response.strip()) == 0:
                self._init_error = f"LLM test failed - None or empty response from model '{self.model_name}'"
                self._initialized = False
                return False
            
            self._initialized = True
            self._init_error = None
            return True
            
        except Exception as e:
            self._init_error = f"LLM initialization error: {e}"
            self._initialized = False
            return False
    
    @property
    def is_initialized(self) -> bool:
        """Check if the generator is properly initialized."""
        return self._initialized
    
    @property
    def init_error(self) -> Optional[str]:
        """Get the initialization error message if any."""
        return self._init_error
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        Rule of thumb: ~4 characters per token for English text.
        """
        return len(text) // 4
    
    def extract_context_length_from_error(self, error_message: str) -> Optional[int]:
        """
        Extract the first number from a context length error message.
        
        Example error: "Reached context length of 4096 tokens with model..."
        Returns: 4096
        """
        try:
            # Look for the first number in the error message
            match = re.search(r'\b(\d+)\b', error_message)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return None
    
    def clean_llm_response(self, response: str) -> str:
        """
        Clean the LLM response by removing channel tags and extracting the final content.
        
        The LLM sometimes returns responses with channel formatting like:
        <|channel|>analysis<|message|>...analysis...<|end|><|start|>assistant<|channel|>final<|message|>...final response...
        
        We want to extract just the final response content.
        """
        if not response:
            return response
        
        # Look for the final message pattern
        final_pattern = r'<\|channel\|>final<\|message\|>(.*?)(?:<\|end\|>|$)'
        match = re.search(final_pattern, response, re.DOTALL)
        
        if match:
            # Extract just the final message content
            cleaned = match.group(1).strip()
            return cleaned
        
        # If no channel tags found, look for assistant response pattern
        assistant_pattern = r'<\|start\|>assistant<\|channel\|>final<\|message\|>(.*?)(?:<\|end\|>|$)'
        match = re.search(assistant_pattern, response, re.DOTALL)
        
        if match:
            cleaned = match.group(1).strip()
            return cleaned
        
        # If no patterns match, try to remove any channel tags that might be present
        # Remove channel control tags
        cleaned = re.sub(r'<\|[^>]+\|>', '', response)
        cleaned = cleaned.strip()
        
        # If the cleaned version is significantly shorter, maybe the original was better
        if len(cleaned) < len(response) * 0.5:
            return response.strip()
        
        return cleaned
    
    def format_event_for_prompt(self, event: Event) -> str:
        """Format a single event for inclusion in the LLM prompt."""
        # Prepare input and output text for this event
        input_text = ""
        output_text = ""
        
        try:
            if event.get("inputs"):
                for key, value in event["inputs"].items():
                    if isinstance(value, str):
                        input_text += f"{key}: {value}\n"
                    else:
                        input_text += f"{key}: {json.dumps(value)}\n"
            
            if event.get("outputs"):
                for key, value in event["outputs"].items():
                    if isinstance(value, str):
                        output_text += f"{key}: {value}\n"
                    else:
                        output_text += f"{key}: {json.dumps(value)}\n"
        except Exception as e:
            input_text = f"Error processing inputs: {e}"
            output_text = f"Error processing outputs: {e}"
        
        # Truncate for this event
        try:
            input_summary = truncate_with_indication(input_text.strip(), 256, from_end=False)
            output_summary = truncate_with_indication(output_text.strip(), 256, from_end=True)
        except Exception:
            input_summary = input_text[:256] + "..." if len(input_text) > 256 else input_text
            output_summary = output_text[:256] + "..." if len(output_text) > 256 else output_text
        
        # Build the purpose/context from the Event structure
        purpose_parts = []
        
        # Add current task
        if event.get("current_task"):
            purpose_parts.append(f"Task: {event['current_task']}")
        
        # Add what was just done
        if event.get("summary_of_what_we_just_did"):
            purpose_parts.append(f"Just did: {event['summary_of_what_we_just_did']}")
        
        # Add what's about to be done
        if event.get("summary_of_what_we_about_to_do"):
            purpose_parts.append(f"About to do: {event['summary_of_what_we_about_to_do']}")
        
        # Join the purpose parts or use a fallback
        purpose_text = " | ".join(purpose_parts) if purpose_parts else "No context provided"
        
        return f"""
  Type: {event.get('type', '')}
  Purpose: {purpose_text}
  Timestamp: {event.get('timestamp', time.time())}
  Duration: {event.get('duration', 0)}s
  Input Details: {input_summary}
  Output Details: {output_summary}
"""
    
    def format_batched_events(self, events_data: List[Dict[str, Any]]) -> str:
        """Format multiple events into a single text block for the LLM."""
        if not events_data:
            return ""
        
        formatted_events = []
        
        for i, item in enumerate(events_data, 1):
            event = item["event"]
            event_block = f"EVENT {i}:{self.format_event_for_prompt(event)}"
            formatted_events.append(event_block)
        
        return "\n".join(formatted_events)
    
    def create_summary_prompt(self, old_summary: str, events_text: str) -> str:
        """Create the LLM prompt for generating a repository architecture summary."""
        return (
            "You are maintaining a PROJECT ARCHITECTURE DOCUMENT for a software repository. "
            "This document serves as a technical reference for future developers working with this codebase. "
            "It contains ONLY factual information about the repository structure, setup, and how to work with it.\\n\\n"
            
            "==== CRITICAL INSTRUCTIONS ====\\n"
            "1. ARCHITECTURE ONLY: Document the repository structure, not development activities\\n"
            "2. STATIC INFORMATION: Include only information that remains stable about the project\\n"
            "3. NO HISTORY: Never include what was done, attempted, discovered, or tried\\n"
            "4. NO PROCESS: Never include commands run, steps taken, or development activities\\n"
            "5. VALIDATION REQUIRED: Check if new information contradicts existing facts\\n"
            "6. CORRECTION MANDATED: Remove any existing information that is now proven incorrect\\n"
            "7. FACTS ONLY: Only include information that is explicitly confirmed by the events\\n\\n"
            
            "==== WHAT TO INCLUDE ====\\n"
            "• Repository location (absolute path)\\n"
            "• Directory structure and file organization\\n"
            "• Key executable files and entry points\\n"
            "• Dependencies and requirements\\n"
            "• Build/test/deployment procedures (if any exist)\\n"
            "• Configuration files and their purposes\\n"
            "• Technology stack and frameworks\\n"
            "• Development environment setup requirements\\n"
            "• Important file locations and their roles\\n"
            "• Any constraints or special requirements\\n\\n"
            
            "==== WHAT TO NEVER INCLUDE ====\\n"
            "• Development activities or work sessions\\n"
            "• Commands that were executed\\n"
            "• Troubleshooting steps or problem-solving\\n"
            "• 'We discovered' or 'We found' statements\\n"
            "• Current work, tasks in progress, or next steps\\n"
            "• Timestamps or chronological information\\n"
            "• Error messages or debugging information\\n"
            "• Development process or methodology\\n"
            "• Personal observations or recommendations\\n\\n"
            
            "==== VALIDATION PROCESS ====\\n"
            "BEFORE writing the updated architecture document:\\n"
            "1. Examine the new events for any factual information about the repository\\n"
            "2. Check if this new information contradicts ANYTHING in the existing document\\n"
            "3. If contradictions exist, REMOVE the incorrect information from the existing document\\n"
            "4. Only add new information that is explicitly confirmed by file contents, directory listings, or configuration details\\n"
            "5. Ensure all paths, file names, and technical details are accurate\\n\\n"
            
            "==== EXAMPLES ====\\n"
            "GOOD: 'Repository located at /Volumes/T9/project/src'\\n"
            "BAD: 'We navigated to /Volumes/T9/project/src and found the code'\\n\\n"
            
            "GOOD: 'Entry point: main.py (runs with python main.py)'\\n"
            "BAD: 'Successfully ran main.py and it worked correctly'\\n\\n"
            
            "GOOD: 'Dependencies: fastmcp, dazllm (install via pip)'\\n"
            "BAD: 'Installed the required dependencies and they are working'\\n\\n"
            
            f"==== CURRENT ARCHITECTURE DOCUMENT ====\\n"
            f"{old_summary}\\n\\n"
            
            f"==== NEW REPOSITORY INFORMATION ====\\n"
            f"{events_text}\\n\\n"
            
            "Now perform the validation process and provide the updated architecture document. "
            "Focus only on the repository structure and setup information. "
            "Remove any incorrect information and add only confirmed facts.\\n\\n"
            
            "Updated Architecture Document:"
        )
    
    def generate_summary(
        self, 
        old_summary: str, 
        events_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate a new summary based on the old summary and new events.
        
        Args:
            old_summary: The existing summary text
            events_data: List of event dictionaries to process
            
        Returns:
            Dictionary with:
            - success: bool indicating if generation succeeded
            - summary: str with the new summary (if successful)
            - error: str with error message (if failed)
            - prompt: str with the generated prompt
            - response: str with the raw LLM response
            - duration: float with generation time in seconds
            - token_estimate: int with estimated token count
        """
        if not self._initialized:
            return {
                "success": False,
                "summary": "",
                "error": "Generator not initialized",
                "prompt": "",
                "response": "",
                "duration": 0.0,
                "token_estimate": 0
            }
        
        start_time = time.time()
        
        try:
            # Format events for the prompt
            events_text = self.format_batched_events(events_data)
            
            # Create the prompt
            prompt = self.create_summary_prompt(old_summary, events_text)
            
            # Estimate tokens
            token_estimate = self.estimate_tokens(prompt)
            
            # Call the LLM
            response = self._llm.chat(prompt)
            
            # Check for None response
            if response is None:
                return {
                    "success": False,
                    "summary": "",
                    "error": "LLM returned None response",
                    "prompt": prompt,
                    "response": "",
                    "duration": time.time() - start_time,
                    "token_estimate": token_estimate
                }
            
            # Clean the response to extract just the content
            cleaned_response = self.clean_llm_response(response)
            new_summary = cleaned_response.strip()
            
            # Validate response length
            if len(new_summary) < 256:
                return {
                    "success": False,
                    "summary": "",
                    "error": f"LLM response too short ({len(new_summary)} chars)",
                    "prompt": prompt,
                    "response": response,
                    "duration": time.time() - start_time,
                    "token_estimate": token_estimate
                }
            
            return {
                "success": True,
                "summary": new_summary,
                "error": None,
                "prompt": prompt,
                "response": response,
                "duration": time.time() - start_time,
                "token_estimate": token_estimate
            }
            
        except Exception as e:
            return {
                "success": False,
                "summary": "",
                "error": str(e),
                "prompt": prompt if 'prompt' in locals() else "",
                "response": "",
                "duration": time.time() - start_time,
                "token_estimate": token_estimate if 'token_estimate' in locals() else 0
            }
    
    def test_llm_connection(self) -> Dict[str, Any]:
        """
        Test the LLM connection with a simple query.
        
        Returns:
            Dictionary with test results including success status and response.
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "Generator not initialized",
                "response": "",
                "duration": 0.0
            }
        
        start_time = time.time()
        
        try:
            test_prompt = "Please respond with exactly: 'LLM connection test successful'"
            response = self._llm.chat(test_prompt)
            
            duration = time.time() - start_time
            
            if response is None:
                return {
                    "success": False,
                    "error": "LLM returned None response",
                    "response": "",
                    "duration": duration
                }
            
            # Clean the response 
            cleaned_response = self.clean_llm_response(response)
            
            return {
                "success": True,
                "error": None,
                "response": cleaned_response,
                "duration": duration
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "response": "",
                "duration": time.time() - start_time
            }


def create_summary_generator(model_name: str = LLM_MODEL_NAME) -> SummaryGenerator:
    """Factory function to create and initialize a SummaryGenerator."""
    generator = SummaryGenerator(model_name)
    return generator
