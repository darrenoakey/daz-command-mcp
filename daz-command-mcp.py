#!/usr/bin/env python3
"""
DAZ Command MCP Server

A simple MCP server that provides command system operations.
Always start with daz_command_start before using other tools.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastmcp import FastMCP


class CommandSystemState:
    """Manages the state of the command system."""
    
    def __init__(self):
        self.is_started = False
        self.current_directory = Path.cwd()
        self.start_time: Optional[float] = None
        self.command_history: List[Dict[str, Any]] = []
    
    def start(self) -> None:
        self.is_started = True
        self.start_time = time.time()
        self.current_directory = Path.cwd()
    
    def change_directory(self, new_path: str) -> Tuple[bool, str]:
        try:
            target_path = Path(new_path).resolve()
            if not target_path.exists():
                return False, f"Directory does not exist: {target_path}"
            if not target_path.is_dir():
                return False, f"Path is not a directory: {target_path}"
            
            self.current_directory = target_path
            os.chdir(str(target_path))
            return True, f"Changed directory to: {target_path}"
        except Exception as e:
            return False, f"Failed to change directory: {str(e)}"
    
    def add_command_to_history(self, command: str, result: Dict[str, Any]) -> None:
        self.command_history.append({
            "timestamp": time.time(),
            "command": command,
            "directory": str(self.current_directory),
            "result": result
        })
        if len(self.command_history) > 100:
            self.command_history.pop(0)


class CommandExecutor:
    """Handles command execution with timeout."""
    
    @staticmethod
    def run_command_with_timeout(
        command: str,
        timeout_seconds: float = 60.0,
        working_directory: Optional[str] = None
    ) -> Dict[str, Any]:
        start_time = time.time()
        result = {
            "command": command,
            "stdout": "",
            "stderr": "",
            "exitcode": None,
            "killed": False,
            "duration": 0.0,
            "working_directory": working_directory or os.getcwd()
        }
        
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=working_directory,
                preexec_fn=os.setsid if os.name != 'nt' else None
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
                result["stdout"] = stdout
                result["stderr"] = stderr
                result["exitcode"] = process.returncode
                
            except subprocess.TimeoutExpired:
                result["killed"] = True
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
                
                try:
                    stdout, stderr = process.communicate(timeout=1.0)
                    result["stdout"] = stdout
                    result["stderr"] = stderr
                except subprocess.TimeoutExpired:
                    result["stdout"] = ""
                    result["stderr"] = "Process killed due to timeout"
                
                result["exitcode"] = -9
                
        except Exception as e:
            result["stderr"] = f"Failed to execute command: {str(e)}"
            result["exitcode"] = -1
        
        result["duration"] = time.time() - start_time
        return result


class FileOperations:
    """Handles file operations."""
    
    @staticmethod
    def read_file(file_path: str) -> Tuple[bool, str, str]:
        try:
            path = Path(file_path)
            if not path.exists():
                return False, f"File does not exist: {path}", ""
            if not path.is_file():
                return False, f"Path is not a file: {path}", ""
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            stat = path.stat()
            file_info = f"Size: {stat.st_size} bytes, Modified: {time.ctime(stat.st_mtime)}"
            return True, content, file_info
            
        except UnicodeDecodeError:
            return False, "File contains binary data or invalid UTF-8", ""
        except Exception as e:
            return False, f"Failed to read file: {str(e)}", ""
    
    @staticmethod
    def write_file(file_path: str, content: str, create_dirs: bool = True) -> Tuple[bool, str]:
        try:
            path = Path(file_path)
            
            if create_dirs and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            stat = path.stat()
            message = f"Successfully wrote {stat.st_size} bytes to {path}"
            return True, message
            
        except Exception as e:
            return False, f"Failed to write file: {str(e)}"


# Global state
command_state = CommandSystemState()

# Initialize FastMCP
mcp = FastMCP(
    "DAZ Command MCP",
)


@mcp.tool(description="Start the DAZ command system. Always call this first before using other command tools. Initializes the system and sets up the current working directory.")
def daz_command_start() -> str:
    command_state.start()
    
    result = {
        "success": True,
        "message": "Command system started successfully",
        "current_directory": str(command_state.current_directory),
        "start_time": command_state.start_time,
        "system_info": {
            "platform": sys.platform,
            "python_version": sys.version.split()[0]
        }
    }
    
    return json.dumps(result, indent=2)


@mcp.tool(description="Write content to a file, creating or overwriting it. Creates parent directories automatically if they don't exist. Requires daz_command_start to be called first.")
def daz_command_write(file_path: str, content: str, create_dirs: bool = True) -> str:
    if not command_state.is_started:
        result = {
            "success": False,
            "error": "Command system not started. Call daz_command_start first."
        }
        return json.dumps(result, indent=2)
    
    success, message = FileOperations.write_file(file_path, content, create_dirs)
    
    result = {
        "success": success,
        "file_path": str(Path(file_path).resolve()) if success else file_path
    }
    
    if success:
        result["message"] = message
    else:
        result["error"] = message
    
    return json.dumps(result, indent=2)


@mcp.tool(description="Read the contents of a text file. Returns the file contents along with file size and modification info. Requires daz_command_start to be called first.")
def daz_command_read(file_path: str) -> str:
    if not command_state.is_started:
        result = {
            "success": False,
            "error": "Command system not started. Call daz_command_start first."
        }
        return json.dumps(result, indent=2)
    
    success, content_or_error, file_info = FileOperations.read_file(file_path)
    
    result = {
        "success": success,
        "file_path": str(Path(file_path).resolve()) if success else file_path
    }
    
    if success:
        result["content"] = content_or_error
        result["file_info"] = file_info
    else:
        result["error"] = content_or_error
    
    return json.dumps(result, indent=2)


@mcp.tool(description="Change the current working directory. Changes to the specified directory for all subsequent operations. Requires daz_command_start to be called first.")
def daz_command_cd(directory: str) -> str:
    if not command_state.is_started:
        result = {
            "success": False,
            "error": "Command system not started. Call daz_command_start first."
        }
        return json.dumps(result, indent=2)
    
    old_directory = str(command_state.current_directory)
    success, message = command_state.change_directory(directory)
    
    result = {
        "success": success,
        "message": message,
        "old_directory": old_directory,
        "new_directory": str(command_state.current_directory)
    }
    
    if not success:
        result["error"] = message
    
    return json.dumps(result, indent=2)


@mcp.tool(description="Execute a shell command with timeout protection. Runs the command and returns stdout, stderr, exit code, and timing info. Commands exceeding the timeout are killed with -9. Requires daz_command_start to be called first.")
def daz_command_run(command: str, timeout: float = 60.0, working_directory: str = None) -> str:
    if not command_state.is_started:
        result = {
            "success": False,
            "error": "Command system not started. Call daz_command_start first."
        }
        return json.dumps(result, indent=2)
    
    if timeout < 0.1 or timeout > 3600:
        result = {
            "success": False,
            "error": "Timeout must be between 0.1 and 3600 seconds"
        }
        return json.dumps(result, indent=2)
    
    if not working_directory:
        working_directory = str(command_state.current_directory)
    
    result = CommandExecutor.run_command_with_timeout(
        command, timeout, working_directory
    )
    
    command_state.add_command_to_history(command, result)
    
    return json.dumps(result, indent=2)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="DAZ Command MCP Server")
    parser.add_argument("--help-tools", action="store_true", 
                       help="Show available tools")
    
    args = parser.parse_args()
    
    if args.help_tools:
        print("DAZ Command MCP Server Tools:")
        print()
        print("1. daz_command_start - Initialize the command system (REQUIRED FIRST)")
        print("2. daz_command_write - Write/overwrite files")
        print("3. daz_command_read  - Read file contents")
        print("4. daz_command_cd    - Change directory")
        print("5. daz_command_run   - Execute commands with timeout")
        print()
        print("Usage: Always call daz_command_start before using other tools!")
        return
    
    mcp.run()


if __name__ == "__main__":
    main()