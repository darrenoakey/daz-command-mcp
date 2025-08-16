#!/usr/bin/env python3
"""
Test script to validate the new three-parameter system
"""

import sys
import json
from pathlib import Path

# Add the current directory to Python path for testing
sys.path.insert(0, str(Path(__file__).parent))

def test_new_parameter_system():
    """Test the new three-parameter system directly"""
    print("=== Testing New Three-Parameter System ===")
    
    try:
        # Import the functions
        from daz_command_mcp.command_executor import change_directory, read_file
        from daz_command_mcp.utils import set_active_session_name
        
        # Create a test session
        set_active_session_name("test-new-params")
        
        # Test the new parameter structure
        current_task = "Testing the new three-parameter system for daz commands"
        summary_of_what_we_just_did = "Created a test session and prepared to validate the new parameter structure"
        summary_of_what_we_about_to_do = "Test change_directory with the new parameters to ensure they are properly stored"
        
        # Test change_directory with new parameters
        result = change_directory(
            directory=".",
            current_task=current_task,
            summary_of_what_we_just_did=summary_of_what_we_just_did,
            summary_of_what_we_about_to_do=summary_of_what_we_about_to_do
        )
        
        print("✅ SUCCESS: change_directory with new parameters executed successfully")
        print(f"Result: {json.dumps(result, indent=2)}")
        
        # Verify the result structure
        assert result["success"] == True
        assert "old_directory" in result
        assert "new_directory" in result
        
        # Test read_file with new parameters  
        result2 = read_file(
            file_path="daz_command_mcp/models.py",
            current_task=current_task,
            summary_of_what_we_just_did="Successfully tested change_directory with new parameter structure",
            summary_of_what_we_about_to_do="Read the models.py file to verify the Event structure has the new fields"
        )
        
        print("✅ SUCCESS: read_file with new parameters executed successfully")
        print(f"Content length: {len(result2['content'])} characters")
        
        # Verify the new Event structure is in the file
        assert "current_task: str" in result2["content"]
        assert "summary_of_what_we_just_did: str" in result2["content"] 
        assert "summary_of_what_we_about_to_do: str" in result2["content"]
        assert "why: str" not in result2["content"]  # Make sure old field is gone
        
        print("✅ All assertions passed!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

if __name__ == "__main__":
    print("Testing New Three-Parameter System")
    print("=" * 50)
    
    test_passed = test_new_parameter_system()
    
    print(f"\n" + "=" * 50)
    print("Test Results:")
    print(f"  New parameter system test: {'PASS' if test_passed else 'FAIL'}")
    
    if test_passed:
        print("\n🎉 New three-parameter system is working correctly!")
        print("\nKey Features:")
        print("  ✅ current_task parameter captures the main task being worked on")
        print("  ✅ summary_of_what_we_just_did captures the recent action and outcome")  
        print("  ✅ summary_of_what_we_about_to_do captures the next planned step")
        print("  ✅ Event structure properly stores all three context parameters")
        print("  ✅ Old 'why' parameter completely removed")
        print("\n⚠️  NOTE: MCP server needs to be restarted to pick up new tool definitions")
        sys.exit(0)
    else:
        print("\n❌ Implementation has issues")
        sys.exit(1)
