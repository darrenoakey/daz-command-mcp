# DAZ Command MCP Server

A Model Context Protocol (MCP) server that provides session-based command execution with intelligent LLM-powered summarization.

## Features

- **Session Management**: Create, open, and manage isolated command execution sessions
- **Command Execution**: Run shell commands with timeout controls and working directory management
- **File Operations**: Read and write text files with comprehensive error handling
- **LLM Summarization**: Automatic session progress tracking using structured LLM responses
- **Event Logging**: Complete audit trail of all operations within sessions
- **Thread-Safe**: Robust concurrent operation with proper synchronization

## Installation

### Prerequisites

- Python 3.8+
- `fastmcp` library
- `pydantic` library  
- `dazllm` library for LLM integration

### Setup

1. Clone this repository:
```bash
git clone https://github.com/yourusername/daz-command-mcp.git
cd daz-command-mcp
```

2. Install dependencies:
```bash
pip install fastmcp pydantic dazllm
```

3. Configure your LLM model in the script (default: `lm-studio:openai/gpt-oss-20b`)

## Usage

### Starting the Server

```bash
python daz-command-mcp.py
```

### Available Tools

#### Session Management

- **`daz_sessions_list()`** - List all sessions and identify the active one
- **`daz_session_create(name, description)`** - Create and activate a new session
- **`daz_session_open(session_id)`** - Open and activate an existing session
- **`daz_session_current()`** - Get details of the currently active session

#### Command & File Operations

All command and file operations require an active session and a `why` parameter explaining the purpose:

- **`daz_command_cd(directory, why)`** - Change working directory
- **`daz_command_read(file_path, why)`** - Read a text file
- **`daz_command_write(file_path, content, why, create_dirs=True)`** - Write a text file
- **`daz_command_run(command, why, timeout=60.0, working_directory=None)`** - Execute shell commands

### Example Workflow

```python
# Create a new session
daz_session_create("Setup Project", "Setting up a new Python project with dependencies")

# Navigate to project directory
daz_command_cd("/path/to/project", "Navigate to project root")

# Run commands
daz_command_run("pip install -r requirements.txt", "Install project dependencies")

# Read configuration
daz_command_read("config.json", "Review current configuration settings")

# Write new file
daz_command_write("setup.py", "...", "Create package setup file")
```

## Architecture

### Session Storage

Sessions are stored as JSON files in the `sessions/` directory with the following structure:

```json
{
  "id": "unique-session-id",
  "name": "Session Name",
  "description": "Detailed description",
  "created_at": 1692123456.789,
  "updated_at": 1692123456.789,
  "summary": "LLM-generated summary",
  "progress": "Current progress status",
  "current_directory": "/current/working/dir",
  "events": [...]
}
```

### Event Logging

Every operation is logged with comprehensive details:

```json
{
  "timestamp": 1692123456.789,
  "type": "run|read|write|cd",
  "why": "User explanation",
  "inputs": {...},
  "outputs": {...},
  "duration": 0.123
}
```

### LLM Integration

The server uses asynchronous LLM processing to maintain session summaries:

- **Background Processing**: Summarization runs in a separate thread
- **Fault Tolerance**: LLM failures don't affect MCP operations
- **Structured Output**: Uses Pydantic models for reliable parsing
- **Configurable Model**: Easy to switch between different LLM providers

## Configuration

### LLM Model

Edit the `LLM_MODEL_NAME` constant in the script:

```python
LLM_MODEL_NAME = "your-model-name"
```

### Session Directory

Sessions are stored in `./sessions/` by default. This can be modified by changing the `SESSIONS_DIR` constant.

## Error Handling

- **Graceful Degradation**: Operations continue even if LLM summarization fails
- **Comprehensive Logging**: All errors are logged to stderr
- **Input Validation**: Robust parameter checking and sanitization
- **File Safety**: Atomic file operations prevent corruption

## Command Line Options

```bash
python daz-command-mcp.py --help-tools  # Show available tools
python daz-command-mcp.py              # Start the MCP server
```

## Integration

This MCP server integrates with Claude Desktop and other MCP-compatible clients. Add it to your MCP configuration:

```json
{
  "mcpServers": {
    "daz-command": {
      "command": "python",
      "args": ["/path/to/daz-command-mcp.py"]
    }
  }
}
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

[Add your license here]

## Dependencies

- **fastmcp**: MCP server framework
- **pydantic**: Data validation and serialization
- **dazllm**: LLM integration library

## Support

For issues and questions, please open an issue on GitHub or contact [your contact information].
