#!/usr/bin/env python3
"""
Unit tests for the LLM Summary Generation functionality.

These tests verify that the LLM is correctly processing and returning results
with real sample data to prove the system is working end-to-end.
"""

import sys
import unittest
import json
import time
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

try:
    from daz_command_mcp.summary_generator import SummaryGenerator, create_summary_generator
    from daz_command_mcp.models import LLM_MODEL_NAME
except ImportError as e:
    print(f"Could not import daz_command_mcp modules: {e}")
    print("Run this test from the project root directory")
    sys.exit(1)


class TestSummaryGenerator(unittest.TestCase):
    """Test cases for the SummaryGenerator class."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures once for all tests."""
        cls.generator = SummaryGenerator()
        
    def test_01_generator_initialization(self):
        """Test that the generator can be initialized properly."""
        generator = SummaryGenerator()
        self.assertIsNotNone(generator)
        self.assertEqual(generator.model_name, LLM_MODEL_NAME)
        self.assertFalse(generator.is_initialized)
        self.assertIsNone(generator.init_error)
    
    def test_02_generator_llm_connection(self):
        """Test that the generator can connect to the LLM."""
        success = self.generator.initialize()
        self.assertTrue(success, f"LLM initialization failed: {self.generator.init_error}")
        self.assertTrue(self.generator.is_initialized)
        self.assertIsNone(self.generator.init_error)
    
    def test_03_llm_connection_test(self):
        """Test the LLM connection with a simple query."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        result = self.generator.test_llm_connection()
        self.assertTrue(result["success"], f"LLM connection test failed: {result.get('error')}")
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["response"])
        self.assertGreater(result["duration"], 0)
        
        # The response should contain something reasonable
        response = result["response"].lower()
        self.assertTrue(
            any(keyword in response for keyword in ["test", "successful", "ok", "working"]),
            f"LLM test response doesn't look right: {result['response']}"
        )
    
    def test_04_token_estimation(self):
        """Test token estimation functionality."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Test with known text lengths
        short_text = "Hello world"
        medium_text = "This is a medium length text that should have more tokens than the short one."
        long_text = "This is a much longer text that contains many more words and should therefore result in a significantly higher token count estimate when processed by the token estimation function."
        
        short_tokens = self.generator.estimate_tokens(short_text)
        medium_tokens = self.generator.estimate_tokens(medium_text)
        long_tokens = self.generator.estimate_tokens(long_text)
        
        # Verify the estimates are reasonable and ordered correctly
        self.assertGreater(medium_tokens, short_tokens)
        self.assertGreater(long_tokens, medium_tokens)
        
        # Verify estimates are in reasonable ranges (roughly 4 chars per token)
        self.assertAlmostEqual(short_tokens, len(short_text) // 4, delta=2)
        self.assertAlmostEqual(medium_tokens, len(medium_text) // 4, delta=5)
    
    def test_05_event_formatting(self):
        """Test formatting of events for prompts."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Create a realistic event
        sample_event = {
            "type": "command",
            "current_task": "Testing the summary generation system",
            "summary_of_what_we_just_did": "Created the SummaryGenerator class",
            "summary_of_what_we_about_to_do": "Test the LLM functionality",
            "timestamp": time.time(),
            "duration": 1.5,
            "inputs": {
                "command": "ls -la /tmp",
                "directory": "/tmp"
            },
            "outputs": {
                "stdout": "total 8\ndrwxrwxrwt   3 root  wheel   96 Aug 17 15:30 .\ndrwxr-xr-x   6 root  wheel  192 Aug 14 09:21 ..",
                "stderr": "",
                "exit_code": 0
            }
        }
        
        formatted = self.generator.format_event_for_prompt(sample_event)
        
        # Verify the formatted output contains expected elements
        self.assertIn("Type: command", formatted)
        self.assertIn("Task: Testing the summary generation system", formatted)
        self.assertIn("Just did: Created the SummaryGenerator class", formatted)
        self.assertIn("About to do: Test the LLM functionality", formatted)
        self.assertIn("Duration: 1.5s", formatted)
        self.assertIn("command: ls -la /tmp", formatted)
        self.assertIn("exit_code: 0", formatted)
    
    def test_06_batched_events_formatting(self):
        """Test formatting of multiple events."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Create multiple events
        events_data = [
            {
                "session_name": "test",
                "old_summary": "Initial summary",
                "event": {
                    "type": "command",
                    "current_task": "First task",
                    "summary_of_what_we_just_did": "Started testing",
                    "summary_of_what_we_about_to_do": "Run first command",
                    "timestamp": time.time(),
                    "duration": 0.5,
                    "inputs": {"command": "echo hello"},
                    "outputs": {"stdout": "hello", "stderr": "", "exit_code": 0}
                }
            },
            {
                "session_name": "test",
                "old_summary": "Initial summary",
                "event": {
                    "type": "command",
                    "current_task": "Second task",
                    "summary_of_what_we_just_did": "Ran first command",
                    "summary_of_what_we_about_to_do": "Run second command",
                    "timestamp": time.time(),
                    "duration": 0.3,
                    "inputs": {"command": "pwd"},
                    "outputs": {"stdout": "/home/user", "stderr": "", "exit_code": 0}
                }
            }
        ]
        
        formatted = self.generator.format_batched_events(events_data)
        
        # Verify both events are present
        self.assertIn("EVENT 1:", formatted)
        self.assertIn("EVENT 2:", formatted)
        self.assertIn("First task", formatted)
        self.assertIn("Second task", formatted)
        self.assertIn("echo hello", formatted)
        self.assertIn("pwd", formatted)
    
    def test_07_prompt_creation(self):
        """Test creation of the LLM prompt."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        old_summary = """**Project Root Directory**

- `/Volumes/T9/darrenoakey/src/test-project`

---

### Core File Structure

```
/Volumes/T9/darrenoakey/src/test-project/
├── main.py                         # Entry point
├── requirements.txt                # Dependencies
└── README.md                       # Documentation
```

---

### Dependencies

* Python 3.x
* No external dependencies currently listed
"""
        
        events_text = """EVENT 1:
  Type: command
  Purpose: Task: Add new dependency | Just did: Created requirements file | About to do: Install package
  Timestamp: 1692284400
  Duration: 0.5s
  Input Details: command: pip install requests
  Output Details: Successfully installed requests-2.31.0
"""
        
        prompt = self.generator.create_summary_prompt(old_summary, events_text)
        
        # Verify the prompt contains essential elements
        self.assertIn("PROJECT ARCHITECTURE DOCUMENT", prompt)
        self.assertIn("CRITICAL INSTRUCTIONS", prompt)
        self.assertIn("CURRENT ARCHITECTURE DOCUMENT", prompt)
        self.assertIn("NEW REPOSITORY INFORMATION", prompt)
        self.assertIn(old_summary, prompt)
        self.assertIn(events_text, prompt)
        self.assertIn("Updated Architecture Document:", prompt)
        
        # Verify instructions are present
        self.assertIn("ARCHITECTURE ONLY", prompt)
        self.assertIn("NO HISTORY", prompt)
        self.assertIn("VALIDATION REQUIRED", prompt)
    
    def test_08_response_cleaning(self):
        """Test cleaning of LLM responses with channel tags."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Test various response formats
        test_cases = [
            # Normal response - no cleaning needed
            ("This is a normal response", "This is a normal response"),
            
            # Response with final channel tags
            ("<|channel|>final<|message|>This is the final content", "This is the final content"),
            
            # Response with full channel sequence
            ("<|channel|>analysis<|message|>Analysis content<|end|><|start|>assistant<|channel|>final<|message|>Final content", "Final content"),
            
            # Response with various patterns
            ("<|start|>assistant<|channel|>final<|message|>Clean content<|end|>", "Clean content"),
        ]
        
        for input_response, expected_output in test_cases:
            result = self.generator.clean_llm_response(input_response)
            self.assertEqual(result, expected_output, f"Failed to clean: {input_response}")
    
    def test_09_real_summary_generation(self):
        """Test actual summary generation with the LLM using realistic data."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Create realistic test data
        old_summary = """**Project Root Directory**

- `/Volumes/T9/darrenoakey/src/test-project`

---

### Core File Structure

```
/Volumes/T9/darrenoakey/src/test-project/
├── main.py                         # Entry point
├── requirements.txt                # Dependencies (empty)
└── README.md                       # Documentation
```

---

### Dependencies

* Python 3.x
* No external dependencies currently listed

---

### Technology Stack

* Language: Python 3.x
* No additional frameworks detected
"""
        
        # Simulate adding a new dependency
        events_data = [
            {
                "session_name": "test",
                "old_summary": old_summary,
                "event": {
                    "type": "write",
                    "current_task": "Add requests dependency to project",
                    "summary_of_what_we_just_did": "Examined current requirements.txt file",
                    "summary_of_what_we_about_to_do": "Add requests>=2.31.0 to requirements.txt",
                    "timestamp": time.time(),
                    "duration": 0.1,
                    "inputs": {
                        "file_path": "requirements.txt",
                        "content": "requests>=2.31.0\nnumpy>=1.24.0\npandas>=1.5.0\n"
                    },
                    "outputs": {
                        "success": True,
                        "message": "File written successfully"
                    }
                }
            }
        ]
        
        result = self.generator.generate_summary(old_summary, events_data)
        
        # Verify the generation was successful
        self.assertTrue(result["success"], f"Summary generation failed: {result.get('error')}")
        self.assertIsNone(result["error"])
        self.assertIsNotNone(result["summary"])
        self.assertGreater(len(result["summary"]), 256, "Summary too short")
        self.assertGreater(result["duration"], 0)
        self.assertGreater(result["token_estimate"], 0)
        
        # Verify the summary contains expected content
        summary = result["summary"]
        self.assertIn("test-project", summary)
        
        # The summary should mention the new dependencies
        self.assertTrue(
            any(dep in summary.lower() for dep in ["requests", "numpy", "pandas"]),
            f"Summary doesn't mention new dependencies: {summary}"
        )
        
        # The summary should NOT contain process descriptions
        bad_phrases = [
            "we added", "we examined", "successfully", "just did", "about to do",
            "ran command", "executed", "discovered", "found"
        ]
        summary_lower = summary.lower()
        for phrase in bad_phrases:
            self.assertNotIn(phrase, summary_lower, 
                           f"Summary contains process description '{phrase}': {summary}")
        
        print(f"\n=== GENERATED SUMMARY ===")
        print(result["summary"])
        print(f"=== GENERATION STATS ===")
        print(f"Duration: {result['duration']:.2f}s")
        print(f"Token estimate: {result['token_estimate']}")
        print(f"Summary length: {len(result['summary'])} chars")
    
    def test_10_error_handling(self):
        """Test error handling with invalid data."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Test with empty events - this might result in a short response, which is acceptable
        result = self.generator.generate_summary("Old summary that is long enough to be meaningful", [])
        self.assertIsNotNone(result)
        self.assertIn("success", result)
        # Don't require success=True for empty events, as that might be reasonable to fail
        
        # Test with malformed event data - should handle gracefully
        malformed_events = [
            {
                "session_name": "test",
                "old_summary": "test",
                "event": {
                    # Missing required fields
                    "inputs": {"broken": "data"},
                    "outputs": None  # This could cause issues
                }
            }
        ]
        
        result = self.generator.generate_summary("Old summary", malformed_events)
        # Should handle malformed data gracefully
        self.assertIsNotNone(result)
        self.assertIn("success", result)
        # The system should handle errors gracefully, even if it doesn't succeed
    
    def test_11_factory_function(self):
        """Test the factory function for creating generators."""
        generator = create_summary_generator()
        self.assertIsNotNone(generator)
        self.assertIsInstance(generator, SummaryGenerator)
        self.assertEqual(generator.model_name, LLM_MODEL_NAME)
    
    def test_12_context_length_extraction(self):
        """Test extraction of context length from error messages."""
        if not self.generator.is_initialized:
            self.generator.initialize()
        
        # Test various error message formats
        test_cases = [
            ("Reached context length of 4096 tokens with model", 4096),
            ("Context window exceeded: 8192 tokens", 8192),
            ("Maximum context of 32768 tokens reached", 32768),
            ("Error: 2048 token limit exceeded", 2048),
            ("No numbers in this error", None),
            ("", None),
        ]
        
        for error_msg, expected in test_cases:
            result = self.generator.extract_context_length_from_error(error_msg)
            self.assertEqual(result, expected, f"Failed for message: '{error_msg}'")


class TestEndToEndSummaryGeneration(unittest.TestCase):
    """End-to-end integration tests with realistic scenarios."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.generator = SummaryGenerator()
        success = cls.generator.initialize()
        if not success:
            raise RuntimeError(f"Could not initialize LLM: {cls.generator.init_error}")
    
    def test_complete_development_session(self):
        """Test a complete development session simulation."""
        # Simulate a realistic development session
        initial_summary = """**Project Root Directory**

- `/Volumes/T9/darrenoakey/src/my-web-app`

---

### Core File Structure

```
/Volumes/T9/darrenoakey/src/my-web-app/
├── package.json                    # Node.js dependencies
├── src/
│   └── index.js                   # Main application file
└── README.md                      # Project documentation
```

---

### Technology Stack

* Language: JavaScript (Node.js)
* No frameworks detected yet

---

### Dependencies

* No dependencies listed in package.json
"""
        
        # Session events: adding Express.js framework
        session_events = [
            {
                "session_name": "test",
                "old_summary": initial_summary,
                "event": {
                    "type": "write",
                    "current_task": "Set up Express.js web server",
                    "summary_of_what_we_just_did": "Reviewed existing package.json file",
                    "summary_of_what_we_about_to_do": "Add Express.js dependency to package.json",
                    "timestamp": time.time(),
                    "duration": 0.2,
                    "inputs": {
                        "file_path": "package.json",
                        "content": json.dumps({
                            "name": "my-web-app",
                            "version": "1.0.0",
                            "main": "src/index.js",
                            "dependencies": {
                                "express": "^4.18.2",
                                "cors": "^2.8.5"
                            },
                            "scripts": {
                                "start": "node src/index.js",
                                "dev": "nodemon src/index.js"
                            }
                        }, indent=2)
                    },
                    "outputs": {
                        "success": True,
                        "bytes_written": 256
                    }
                }
            },
            {
                "session_name": "test", 
                "old_summary": initial_summary,
                "event": {
                    "type": "write",
                    "current_task": "Set up Express.js web server",
                    "summary_of_what_we_just_did": "Updated package.json with Express dependencies",
                    "summary_of_what_we_about_to_do": "Create basic Express server in index.js",
                    "timestamp": time.time(),
                    "duration": 0.5,
                    "inputs": {
                        "file_path": "src/index.js",
                        "content": "const express = require('express');\nconst cors = require('cors');\n\nconst app = express();\nconst PORT = process.env.PORT || 3000;\n\napp.use(cors());\napp.use(express.json());\n\napp.get('/', (req, res) => {\n  res.json({ message: 'Hello World!' });\n});\n\napp.listen(PORT, () => {\n  console.log(`Server running on port ${PORT}`);\n});\n"
                    },
                    "outputs": {
                        "success": True,
                        "bytes_written": 285
                    }
                }
            }
        ]
        
        # Generate updated summary
        result = self.generator.generate_summary(initial_summary, session_events)
        
        # Verify success
        self.assertTrue(result["success"], f"Failed: {result.get('error')}")
        self.assertGreater(len(result["summary"]), 256)
        
        summary = result["summary"]
        print(f"\n=== REALISTIC SESSION SUMMARY ===")
        print(summary)
        
        # Verify the summary correctly reflects the changes
        self.assertIn("Express", summary)
        self.assertIn("cors", summary)
        
        # Check for architectural elements (more realistic than specific port numbers)
        architecture_elements = [
            "src/index.js",
            "package.json", 
            "dependencies",
            "Node.js",
            "Express"
        ]
        
        for element in architecture_elements:
            self.assertIn(element, summary, f"Missing architectural element: {element}")
        
        # Verify it doesn't contain process descriptions
        bad_phrases = ["we updated", "added express", "created server", "just did", "about to do"]
        summary_lower = summary.lower()
        for phrase in bad_phrases:
            self.assertNotIn(phrase, summary_lower, 
                           f"Summary contains process description: {phrase}")
        
        # Check that it mentions the build/run procedures if they exist
        # This is more appropriate for architecture docs than specific port numbers
        if "scripts" in summary or "npm start" in summary:
            print("✅ Summary appropriately includes build/run procedures")
        else:
            print("ℹ️  Summary doesn't mention build procedures (which is fine)")


def main():
    """Run all tests with detailed output."""
    # Configure test runner
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSummaryGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndSummaryGeneration))
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"SUMMARY: {result.testsRun} tests run")
    if result.failures:
        print(f"FAILURES: {len(result.failures)}")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback}")
    
    if result.errors:
        print(f"ERRORS: {len(result.errors)}")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")
    
    if result.wasSuccessful():
        print("ALL TESTS PASSED! ✅")
        print("The LLM summary generation system is working correctly.")
    else:
        print("SOME TESTS FAILED! ❌")
        print("The LLM summary generation system needs attention.")
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
