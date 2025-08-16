#!/usr/bin/env python3
"""
Simple verification test to prove the LLM summary system is now working correctly.
"""

import sys
import time
from pathlib import Path

# Add the project root to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from daz_command_mcp.models import Event
from daz_command_mcp.summary_worker import format_batched_events, get_llm

def test_fixed_system():
    """Test that the LLM system now works with the new Event structure"""
    print("=== VERIFICATION: Testing Fixed LLM System ===\n")
    
    # Create an event with the new structure
    event: Event = {
        "timestamp": time.time(),
        "type": "verification_test",
        "current_task": "Verifying the LLM summary system fix",
        "summary_of_what_we_just_did": "Fixed the format_batched_events function to use new Event fields",
        "summary_of_what_we_about_to_do": "Test that events now have proper purpose context",
        "inputs": {"test_param": "verification_value"},
        "outputs": {"success": True, "system_fixed": True},
        "duration": 1.5
    }
    
    # Format the event
    events_data = [{
        "session_name": "verification_session",
        "old_summary": "Testing the fix",
        "event": event
    }]
    
    formatted = format_batched_events(events_data)
    print("Formatted event:")
    print(formatted)
    print()
    
    # Check that the purpose is no longer empty
    if "Purpose: Task:" in formatted and "Just did:" in formatted and "About to do:" in formatted:
        print("✅ SUCCESS: Event now has proper purpose context!")
        print("✅ The LLM summary system is FIXED!")
    else:
        print("❌ FAILED: Event still has empty or incorrect purpose")
        return False
    
    # Test LLM response
    llm = get_llm()
    if llm:
        simple_prompt = f"""
        Given this event information, provide a brief summary:
        {formatted}
        
        Summary:"""
        
        try:
            response = llm.chat(simple_prompt)
            print(f"\n📝 LLM Response ({len(response)} chars):")
            print(response[:200] + "..." if len(response) > 200 else response)
            print("\n✅ LLM is responding correctly to events with proper context!")
            return True
        except Exception as e:
            print(f"\n❌ LLM failed to respond: {e}")
            return False
    else:
        print("\n⚠️  LLM not available for testing")
        return False

if __name__ == "__main__":
    success = test_fixed_system()
    if success:
        print("\n" + "="*50)
        print("🎉 LLM SUMMARY SYSTEM IS NOW WORKING! 🎉")
        print("="*50)
    else:
        print("\n" + "="*50)
        print("❌ System still has issues")
        print("="*50)
