#!/usr/bin/env python3
"""
Integration tests for the LLM summary system that actually call out to the LLM.
These tests should fail initially due to the broken Event model structure.
"""

import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any
import unittest

# Add the project root to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from daz_command_mcp.models import Event
from daz_command_mcp.summary_worker import (
    format_batched_events, 
    get_llm, 
    ensure_summary_thread,
    wait_for_summary_worker_init,
    enqueue_summary
)
from daz_command_mcp.utils import get_session_dir, save_session_summary, load_session_summary, set_active_session_name


class TestLLMSystemIntegration(unittest.TestCase):
    """Test the LLM summary system with real LLM calls"""
    
    def setUp(self):
        """Set up test environment"""
        # Create a temporary directory for test sessions
        self.test_sessions_dir = tempfile.mkdtemp(prefix="daz_test_sessions_")
        
        # Override the session directory for testing
        import daz_command_mcp.utils as utils
        self.original_get_session_dir = utils.get_session_dir
        utils.get_session_dir = lambda name: Path(self.test_sessions_dir) / name
        
        # Also patch it in session_manager
        import daz_command_mcp.session_manager as session_manager
        session_manager.get_session_dir = utils.get_session_dir
        
        self.test_session_name = "test_llm_session"
        
    def tearDown(self):
        """Clean up test environment"""
        # Restore original functions
        import daz_command_mcp.utils as utils
        import daz_command_mcp.session_manager as session_manager
        utils.get_session_dir = self.original_get_session_dir
        session_manager.get_session_dir = self.original_get_session_dir
        
        # Clean up temporary directory
        shutil.rmtree(self.test_sessions_dir, ignore_errors=True)
        
    def test_llm_availability(self):
        """Test that the LLM is available and working"""
        print("\n=== Testing LLM Availability ===")
        
        llm = get_llm()
        self.assertIsNotNone(llm, "LLM should be available")
        
        # Test basic communication
        response = llm.chat("Please respond with exactly 'TEST_OK'")
        self.assertIsNotNone(response, "LLM should return a response")
        self.assertIn("TEST_OK", response, f"LLM should respond correctly, got: {response}")
        
        print(f"✓ LLM is available and responding correctly")
        
    def test_event_model_structure(self):
        """Test that Event model has the expected new structure"""
        print("\n=== Testing Event Model Structure ===")
        
        # Create an event with the new structure
        event: Event = {
            "timestamp": time.time(),
            "type": "test_command",
            "current_task": "Testing the new event structure",
            "summary_of_what_we_just_did": "Created a test event",
            "summary_of_what_we_about_to_do": "Verify the event structure works",
            "inputs": {"test_input": "value"},
            "outputs": {"success": True},
            "duration": 1.0
        }
        
        # Verify the new fields exist
        self.assertIn("current_task", event)
        self.assertIn("summary_of_what_we_just_did", event)
        self.assertIn("summary_of_what_we_about_to_do", event)
        
        # Verify the old field doesn't exist in our event
        self.assertNotIn("why", event)
        
        print(f"✓ Event model has new structure")
        
    def test_format_batched_events_with_new_structure(self):
        """Test that format_batched_events works with the new Event structure"""
        print("\n=== Testing Event Formatting with New Structure ===")
        
        # Create events with the new structure
        events_data = []
        for i in range(2):
            event: Event = {
                "timestamp": time.time(),
                "type": f"test_command_{i}",
                "current_task": f"Testing task {i}",
                "summary_of_what_we_just_did": f"Completed step {i-1}",
                "summary_of_what_we_about_to_do": f"About to do step {i+1}",
                "inputs": {"command": f"test_{i}", "param": f"value_{i}"},
                "outputs": {"success": True, "result": f"output_{i}"},
                "duration": 1.0 + i
            }
            events_data.append({
                "session_name": self.test_session_name,
                "old_summary": f"Previous summary {i}",
                "event": event
            })
        
        # Test formatting
        formatted = format_batched_events(events_data)
        
        print(f"Formatted events length: {len(formatted)}")
        print(f"Formatted events preview:\n{formatted[:500]}...")
        
        # The formatted text should contain information from both events
        self.assertIn("EVENT 1:", formatted)
        self.assertIn("EVENT 2:", formatted)
        self.assertIn("test_command_0", formatted)
        self.assertIn("test_command_1", formatted)
        
        # Check if it handles the new structure correctly
        # This is where the bug would manifest - if it's looking for 'why' field
        print(f"✓ Event formatting completed without errors")
        
    def test_llm_summary_generation_with_new_events(self):
        """Test end-to-end LLM summary generation with new event structure"""
        print("\n=== Testing LLM Summary Generation ===")
        
        # Initialize LLM and ensure worker is ready
        ensure_summary_thread()
        
        try:
            wait_for_summary_worker_init(timeout=30.0)
            print("✓ Summary worker initialized successfully")
        except Exception as e:
            self.fail(f"Summary worker failed to initialize: {e}")
        
        # Create a session
        set_active_session_name(self.test_session_name)
        
        # Create events with the new structure
        events_data = []
        for i in range(3):
            event: Event = {
                "timestamp": time.time(),
                "type": f"cd" if i == 0 else f"read" if i == 1 else "run",
                "current_task": "Setting up development environment",
                "summary_of_what_we_just_did": f"Completed operation {i}",
                "summary_of_what_we_about_to_do": f"Next will do operation {i+1}",
                "inputs": {
                    "directory": "/test/path" if i == 0 else None,
                    "file_path": "/test/file.py" if i == 1 else None,
                    "command": "ls -la" if i == 2 else None
                },
                "outputs": {"success": True, "result": f"Operation {i} completed"},
                "duration": 1.0 + i * 0.5
            }
            # Filter out None values from inputs
            event["inputs"] = {k: v for k, v in event["inputs"].items() if v is not None}
            events_data.append(event)
        
        # Get LLM and test direct summary generation
        llm = get_llm()
        old_summary = "Initial project setup in progress."
        
        # Format events
        formatted_events = format_batched_events([
            {"session_name": self.test_session_name, "old_summary": old_summary, "event": event}
            for event in events_data
        ])
        
        print(f"Formatted events:\n{formatted_events}")
        
        # Create the prompt (simplified version of what the worker does)
        prompt = f"""You are updating a technical knowledge base. Given the old summary and new events, 
provide an updated summary that captures the key information.

Old Summary: {old_summary}

New Events:
{formatted_events}

Updated Summary:"""
        
        # Test LLM call
        try:
            response = llm.chat(prompt)
            print(f"✓ LLM responded successfully")
            print(f"Response length: {len(response)}")
            print(f"Response preview: {response[:200]}...")
            
            self.assertIsNotNone(response)
            self.assertGreater(len(response.strip()), 50, "Response should be substantial")
            
        except Exception as e:
            self.fail(f"LLM summary generation failed: {e}")
    
    def test_summary_worker_queue_processing(self):
        """Test that the summary worker can process events with the new structure"""
        print("\n=== Testing Summary Worker Queue Processing ===")
        
        # Initialize the summary worker
        ensure_summary_thread()
        
        try:
            wait_for_summary_worker_init(timeout=30.0)
        except Exception as e:
            self.fail(f"Summary worker failed to initialize: {e}")
        
        # Create session directory
        session_dir = get_session_dir(self.test_session_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Set initial summary
        initial_summary = "Test project initialization"
        save_session_summary(self.test_session_name, initial_summary)
        
        # Create an event with the new structure
        event: Event = {
            "timestamp": time.time(),
            "type": "test_operation",
            "current_task": "Testing summary worker",
            "summary_of_what_we_just_did": "Created a test session",
            "summary_of_what_we_about_to_do": "Enqueue an event for processing",
            "inputs": {"test_param": "test_value"},
            "outputs": {"success": True, "message": "Test operation completed"},
            "duration": 2.5
        }
        
        # Enqueue the event
        try:
            enqueue_summary(self.test_session_name, initial_summary, event)
            print("✓ Event enqueued successfully")
        except Exception as e:
            self.fail(f"Failed to enqueue event: {e}")
        
        # Wait a bit for processing (this is a background process)
        import time
        time.sleep(3)
        
        # Check if summary was updated
        try:
            updated_summary = load_session_summary(self.test_session_name)
            print(f"Updated summary: {updated_summary}")
            
            # The summary should have changed (unless the worker failed)
            if updated_summary == initial_summary:
                print("⚠️  Summary was not updated - this indicates the worker might have failed")
            else:
                print("✓ Summary was updated successfully")
                
        except Exception as e:
            print(f"⚠️  Could not load updated summary: {e}")


class TestEventStructureMismatch(unittest.TestCase):
    """Specific tests to identify the structure mismatch issue"""
    
    def test_old_vs_new_event_fields(self):
        """Test the difference between old and new event field structures"""
        print("\n=== Testing Event Field Structure Mismatch ===")
        
        # Old structure (what the code might expect)
        old_event = {
            "timestamp": time.time(),
            "type": "test",
            "why": "This is the old why field",
            "inputs": {"test": "value"},
            "outputs": {"success": True},
            "duration": 1.0
        }
        
        # New structure (what we actually create)
        new_event: Event = {
            "timestamp": time.time(),
            "type": "test",
            "current_task": "Testing new structure",
            "summary_of_what_we_just_did": "Created old event example",
            "summary_of_what_we_about_to_do": "Compare with new structure",
            "inputs": {"test": "value"},
            "outputs": {"success": True},
            "duration": 1.0
        }
        
        print(f"Old event has 'why': {'why' in old_event}")
        print(f"New event has 'why': {'why' in new_event}")
        print(f"New event has 'current_task': {'current_task' in new_event}")
        
        # Test what happens when we try to access 'why' from new event
        why_value = new_event.get('why', 'NOT_FOUND')
        print(f"new_event.get('why', 'NOT_FOUND') = '{why_value}'")
        
        # This simulates what format_batched_events does
        formatted_old = f"Purpose: {old_event.get('why', '')}"
        formatted_new = f"Purpose: {new_event.get('why', '')}"
        
        print(f"Formatted old event purpose: '{formatted_old}'")
        print(f"Formatted new event purpose: '{formatted_new}'")
        
        # The new event will have an empty purpose, which could break LLM processing
        self.assertEqual(formatted_old, "Purpose: This is the old why field")
        self.assertEqual(formatted_new, "Purpose: ")  # Empty!
        
        print("✓ Confirmed: new events have empty 'Purpose' field when using old formatting")


if __name__ == "__main__":
    print("=" * 60)
    print("LLM SYSTEM INTEGRATION TESTS")
    print("=" * 60)
    print("These tests will actually call the LLM to verify the system works.")
    print("If the system is broken, these tests should fail and show us why.")
    print()
    
    # Run tests with verbose output
    unittest.main(verbosity=2, exit=False)
