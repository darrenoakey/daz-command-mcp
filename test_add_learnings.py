#!/usr/bin/env python3
"""
Test script to demonstrate the new add_learnings functionality
"""

import sys
import json
from pathlib import Path

# Add the current directory to Python path for testing
sys.path.insert(0, str(Path(__file__).parent))

def test_add_learnings():
    """Test the add_learnings function"""
    print("=== Testing add_learnings Function ===")
    
    try:
        # Import the function
        from daz_command_mcp.command_executor import add_learnings
        from daz_command_mcp.utils import set_active_session_name
        
        # Create a mock session (this would normally be done via session creation)
        set_active_session_name("test-learning-session")
        
        # Test the function
        learning_info = """
        Important Discovery: Project Structure Found
        - Full project path: /Volumes/T9/darrenoakey/src/daz-command-mcp
        - Main module structure: daz_command_mcp/ contains all core functionality
        - Key files: main.py (entry point), summary_worker.py (LLM integration), mcp_tools.py (API endpoints)
        - Summary worker uses threading.Event for initialization signaling
        - LLM model configured as: lm-studio:openai/gpt-oss-20b
        - Session data stored in: daz_command_mcp/sessions/<session_name>/
        """
        
        result = add_learnings(learning_info.strip())
        
        print("✅ SUCCESS: add_learnings function executed successfully")
        print(f"Result: {json.dumps(result, indent=2)}")
        
        # Verify the key characteristics
        assert result["success"] == True
        assert "Learning information added to session context" in result["message"]
        assert result["info_length"] > 0
        assert "session" in result
        
        print("✅ All assertions passed!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def show_function_documentation():
    """Display the function documentation"""
    print("\n=== add_learnings Function Documentation ===")
    
    from daz_command_mcp.command_executor import add_learnings
    
    print(f"Function Name: {add_learnings.__name__}")
    print(f"Docstring:")
    print(add_learnings.__doc__)
    
    print("\n=== MCP Tool Documentation ===")
    
    from daz_command_mcp.mcp_tools import daz_add_learnings
    
    print(f"MCP Tool Name: {daz_add_learnings.__name__}")
    print(f"Docstring:")
    print(daz_add_learnings.__doc__)

if __name__ == "__main__":
    print("Testing add_learnings Implementation")
    print("=" * 50)
    
    # Show documentation
    show_function_documentation()
    
    # Test functionality
    test_passed = test_add_learnings()
    
    print(f"\n" + "=" * 50)
    print("Test Results:")
    print(f"  add_learnings function test: {'PASS' if test_passed else 'FAIL'}")
    
    if test_passed:
        print("\n🎉 add_learnings implementation is working correctly!")
        print("\nKey Features:")
        print("  ✅ No 'why' parameter required (unique among all commands)")
        print("  ✅ Doesn't execute any system commands")  
        print("  ✅ Just adds information to LLM processing queue")
        print("  ✅ Perfect for capturing discovered paths, insights, and context")
        sys.exit(0)
    else:
        print("\n❌ Implementation has issues")
        sys.exit(1)
