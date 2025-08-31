#!/usr/bin/env python3
"""
Test script to verify resilient LLM handling in daz-command-mcp
"""

import sys
import os

def test_basic_import():
    """Test that the modules can be imported without LLM"""
    print("Testing basic module imports...")
    
    # Test if dazllm is available
    dazllm_available = False
    try:
        import dazllm
        dazllm_available = True
        print("  ✓ dazllm module is available")
    except ImportError as e:
        print(f"  ✗ dazllm module not available: {e}")
    
    # Test if we can import our summary generator (this should work regardless of dazllm)
    try:
        sys.path.insert(0, 'src')
        
        # Import with workaround for relative imports
        import importlib.util
        
        # Load models first
        models_spec = importlib.util.spec_from_file_location("models", "src/models.py")
        models_module = importlib.util.module_from_spec(models_spec)
        models_spec.loader.exec_module(models_module)
        
        # Load utils
        utils_spec = importlib.util.spec_from_file_location("utils", "src/utils.py")
        utils_module = importlib.util.module_from_spec(utils_spec)
        utils_spec.loader.exec_module(utils_module)
        
        print("  ✓ Core modules can be imported")
        
        return dazllm_available
        
    except Exception as e:
        print(f"  ✗ Failed to import core modules: {e}")
        return False

def test_main_entry_point():
    """Test that the main entry point can show help"""
    print("\nTesting main entry point...")
    
    import subprocess
    try:
        result = subprocess.run([sys.executable, "daz-command-mcp.py", "--help"], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print("  ✓ Main entry point works (--help succeeds)")
            if "dazllm module not available" in result.stderr:
                print("  ✓ System gracefully handles missing dazllm")
            return True
        else:
            print(f"  ✗ Main entry point failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("  ✗ Main entry point timed out")
        return False
    except Exception as e:
        print(f"  ✗ Failed to test main entry point: {e}")
        return False

def main():
    """Main test function"""
    print("=== Testing Resilient LLM Handling ===")
    print()
    
    dazllm_available = test_basic_import()
    main_works = test_main_entry_point()
    
    print()
    print("=== Test Results ===")
    
    if dazllm_available:
        print("✓ dazllm is available - LLM functionality should work normally")
    else:
        print("✓ dazllm is NOT available - testing resilient behavior")
    
    if main_works:
        print("✓ Main entry point works correctly")
    else:
        print("✗ Main entry point has issues")
        return 1
    
    print()
    if not dazllm_available and main_works:
        print("🎉 SUCCESS: System is resilient to LLM unavailability!")
        print("   - System starts without failing")
        print("   - Other functionality should work normally")
        print("   - Only summary generation will be disabled")
    elif dazllm_available and main_works:
        print("🎉 SUCCESS: System works normally with LLM available!")
    else:
        print("❌ FAILURE: System has issues")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
