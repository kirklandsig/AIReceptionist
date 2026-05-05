# Development Guide

This guide covers local development setup, running the project, testing, code organization, coding standards, and how to contribute to AI Receptionist.

---

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Project Structure](#project-structure)
- [Running the Agent Locally](#running-the-agent-locally)
- [Testing](#testing)
- [Code Organization](#code-organization)
  - [config.py](#configpy)
  - [prompts.py](#promptspy)
  - [messages.py](#messagespy)
  - [agent.py](#agentpy)
- [Adding a New Function Tool](#adding-a-new-function-tool)
- [Adding a New Configuration Field](#adding-a-new-configuration-field)
- [Coding Standards](#coding-standards)
- [Dependency Management](#dependency-management)
- [Contributing](#contributing)
- [Common Development Tasks](#common-development-tasks)

---

## Development Environment Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/your-org/ai-receptionist.git
cd ai-receptionist
```

### Step 2: Verify Python Version

Python 3.11 or later is required. The project has been tested on Python 3.14.2 (Windows 11).

```bash
python --version
# Python 3.11.x or later
```

### Step 3: Create a Virtual Environment

```bash
python -m venv .venv

# Activate on Linux/macOS
source .venv/bin/activate

# Activate on Windows (Command Prompt)
.venv\Scripts\activate

# Activate on Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Activate on Windows (Git Bash)
source .venv/Scripts/activate
```

### Step 4: Install Dependencies

The project uses `hatchling` as its build backend. Install in editable mode for development:

```bash
pip install -e .
```

This installs all dependencies defined in `pyproject.toml`:

| Dependency | Purpose |
|-----------|---------|
| `livekit-agents` | LiveKit Agents SDK — agent lifecycle, session management |
| `livekit-plugins-openai` | OpenAI Realtime API integration for LiveKit |
| `livekit-plugins-noise-cancellation` | Audio noise cancellation |
| `pydantic` | Data validation for configuration models |
| `pyyaml` | YAML configuration file parsing |
| `python-dotenv` | Environment variable loading from `.env` files |

### Step 5: Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your actual credentials:

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
OPENAI_API_KEY=sk-your-openai-key
```

`OPENAI_API_KEY` is optional when your test business YAML uses
`voice.auth.type: "oauth_codex"`. For that path, run
`python -m receptionist.voice setup <business>` and see
[ChatGPT OAuth Setup](chatgpt-oauth-setup.md).

**For testing without LiveKit/OpenAI**: You can run the unit tests without these credentials. They are only needed for running the agent itself.

### Step 6: Create a Business Configuration

```bash
cp config/businesses/example-dental.yaml config/businesses/my-test.yaml
```

Edit `my-test.yaml` as needed. See [Configuration Reference](configuration-reference.md) for details.

---

## Project Structure

```
AIReceptionist/
├── README.md                         # Project overview
├── pyproject.toml                    # Build configuration and dependencies
├── .env.example                      # Environment variable template
│
├── receptionist/                     # Main package
│   ├── __init__.py                   # Package init
│   ├── agent.py                      # Core agent logic (entry point)
│   ├── config.py                     # Pydantic configuration models
│   ├── prompts.py                    # System prompt construction
│   └── messages.py                   # Message taking and delivery
│
├── config/                           # Configuration directory
│   └── businesses/                   # Business YAML configs
│       └── example-dental.yaml       # Example configuration
│
├── tests/                            # Test suite
│   ├── test_config.py                # Config model tests (6 tests)
│   ├── test_prompts.py               # Prompt generation tests (6 tests)
│   └── test_messages.py              # Message handling tests (3 tests)
│
├── messages/                         # Default message storage directory
│
└── docs/                             # Documentation
    └── plans/                        # Design documents and implementation plans
```

---

## Running the Agent Locally

### Development Mode

```bash
python -m receptionist.agent dev
```

Development mode provides:
- Verbose logging output
- Helpful for debugging configuration and connection issues

### Making Test Calls

To test the agent with actual phone calls:

1. Ensure your LiveKit server is running and SIP trunk is configured.
2. Start the agent in dev mode.
3. Call the phone number associated with your SIP trunk.
4. The agent will answer and you can test the conversation.

### Testing Without a Phone

For development without a full SIP setup, you can use:

1. **LiveKit Meet**: Connect to the same LiveKit room as the agent using a WebRTC client.
2. **LiveKit CLI**: Use `lk room join` to join the room as a participant.

Note that noise cancellation mode differs between SIP and WebRTC connections (BVCTelephony vs. BVC).

---

## Testing

### Running All Tests

```bash
python -m pytest tests/ -v
```

Expected output: 15 tests, all passing.

```
tests/test_config.py::test_... PASSED       (6 tests)
tests/test_prompts.py::test_... PASSED      (6 tests)
tests/test_messages.py::test_... PASSED     (3 tests)

========================= 15 passed =========================
```

### Running Specific Test Files

```bash
# Config tests only
python -m pytest tests/test_config.py -v

# Prompt tests only
python -m pytest tests/test_prompts.py -v

# Message tests only
python -m pytest tests/test_messages.py -v
```

### Running a Single Test

```bash
python -m pytest tests/test_config.py::test_function_name -v
```

### Test Coverage

The test suite covers:

**`test_config.py` (6 tests)**:
- Valid configuration loading and validation
- Invalid field rejection
- HH:MM time format validation
- "closed" day handling
- Cross-field validation for message delivery settings
- YAML string parsing via `from_yaml_string`

**`test_prompts.py` (6 tests)**:
- System prompt contains business name and type
- Hours schedule is included in the prompt
- Routing departments appear in the prompt
- FAQ content is embedded in the prompt
- Personality instructions are included
- After-hours message is present

**`test_messages.py` (3 tests)**:
- Message dataclass creation and timestamp auto-population
- File-based message saving creates correct JSON files
- Message content matches expected structure

### Writing New Tests

Place test files in the `tests/` directory with the `test_` prefix. Follow the existing patterns:

```python
# tests/test_feature.py

from receptionist.config import BusinessConfig, load_config
from receptionist.prompts import build_system_prompt


def test_my_feature():
    """Describe what this test verifies."""
    config = BusinessConfig.from_yaml_string("""
    business:
      name: "Test Business"
      type: "test"
      timezone: "UTC"
    # ... minimal config for the test
    """)

    result = my_function(config)

    assert result == expected_value
```

**Testing guidelines**:
- Each test should verify one specific behavior.
- Use descriptive test names that explain what is being tested.
- Use `BusinessConfig.from_yaml_string()` for creating test configs.
- Keep tests independent — no shared mutable state between tests.
- Test both happy paths and error cases.

---

## Code Organization

### config.py

**Responsibility**: Define and validate configuration data structures.

**Key classes and their relationships**:

```
BusinessConfig (top-level)
├── business: BusinessInfo
│   ├── name: str
│   ├── type: str
│   └── timezone: str
├── voice: VoiceConfig
│   └── voice_id: str = "coral"
├── greeting: str
├── personality: str
├── hours: WeeklyHours
│   └── monday..sunday: DayHours | None
│       ├── open: str  (HH:MM)
│       └── close: str (HH:MM)
├── after_hours_message: str
├── routing: list[RoutingEntry]
│   ├── name: str
│   ├── number: str
│   └── description: str
├── faqs: list[FAQEntry]
│   ├── question: str
│   └── answer: str
└── messages: MessagesConfig
    ├── delivery: Literal["file", "webhook"]
    ├── file_path: str | None
    └── webhook_url: str | None
```

**Key patterns**:
- Pydantic `BaseModel` for all config classes.
- `DayHours` has a validator for HH:MM format.
- `WeeklyHours` uses `Optional[DayHours]` where `None` means "closed."
- `MessagesConfig` uses a model validator for cross-field dependency checks.
- `BusinessConfig.from_yaml_string()` is a classmethod for convenient YAML loading.
- `load_config(path)` is a standalone function that reads a file and returns a validated config.

### prompts.py

**Responsibility**: Transform a `BusinessConfig` into a comprehensive LLM system prompt.

**Key function**: `build_system_prompt(config: BusinessConfig) -> str`

The prompt is constructed by assembling sections:
1. Role definition (business name and type)
2. Personality block
3. Hours schedule (formatted as a readable list)
4. After-hours instructions
5. Routing information (department names and descriptions)
6. Tool usage guidelines
7. FAQ knowledge base
8. Behavioral constraints

**Design notes**:
- The prompt is a plain string, not a template engine. This keeps dependencies minimal and the logic transparent.
- Each section is clearly delimited so the LLM can parse it reliably.
- FAQ content is duplicated in the prompt (in addition to being available via the `lookup_faq` tool) so the LLM can answer common questions without a tool call.

### messages.py

**Responsibility**: Handle message persistence.

**Key components**:
- `Message` dataclass with auto-timestamp.
- `save_message(message, config)` dispatches to the correct backend.
- `_save_to_file(message, path)` writes JSON with microsecond-precision filenames.
- `_send_webhook(message, url)` is a placeholder for future implementation.

**Design notes**:
- Messages are saved as individual JSON files (not appended to a log) for simplicity and atomic writes.
- Microsecond timestamps in filenames prevent collisions even under high load.
- The `asyncio.to_thread()` wrapper in `agent.py` ensures file I/O does not block the event loop.

### agent.py

**Responsibility**: Orchestrate everything — load config, build prompt, create agent session, handle calls.

**Key components**:

1. **`load_business_config(ctx)`**: Resolves which YAML config to use.
   - Checks job metadata for "config" key.
   - Validates the slug against `^[a-zA-Z0-9_-]+$`.
   - Falls back to first YAML file in `config/businesses/`.

2. **`Receptionist(Agent)`**: The agent class with:
   - `on_enter()`: Delivers the greeting.
   - `lookup_faq(question)`: Searches FAQ entries by substring.
   - `transfer_call(department)`: Initiates SIP transfer.
   - `take_message(caller_name, message, callback_number)`: Saves message.
   - `get_business_hours()`: Returns timezone-aware status.
   - `_get_caller_identity()`: Finds SIP participant in the room.

3. **`handle_call(ctx)`**: Session handler that wires everything together.

4. **Entry point**: `python -m receptionist.agent` invokes the LiveKit CLI.

---

## Adding a New Function Tool

Function tools are methods on the `Receptionist` class that are exposed to the OpenAI Realtime model. Here is how to add a new one:

### Step 1: Define the Tool Method

In `agent.py`, add a new method to the `Receptionist` class:

```python
class Receptionist(Agent):
    # ... existing tools ...

    @function_tool()
    async def my_new_tool(self, parameter: str) -> str:
        """Description of what this tool does.

        The docstring is sent to the LLM as the tool description.
        Make it clear and specific about when to use this tool.

        Args:
            parameter: Description of the parameter.
        """
        # Implement your logic here
        result = do_something(parameter, self.config)
        return f"Result: {result}"
```

### Step 2: Update the System Prompt

In `prompts.py`, add instructions for when and how the LLM should use the new tool. Add a section in `build_system_prompt()`:

```python
def build_system_prompt(config):
    # ... existing sections ...

    prompt += "\n## My New Tool\n"
    prompt += "Use the my_new_tool function when the caller asks about...\n"

    # ... rest of prompt ...
```

### Step 3: Add Configuration (if needed)

If the tool needs configuration data, add new fields to the appropriate Pydantic model in `config.py`:

```python
class BusinessConfig(BaseModel):
    # ... existing fields ...
    my_new_setting: str = "default_value"
```

Update the YAML example and documentation accordingly.

### Step 4: Write Tests

Add tests to verify:
- The tool returns correct results for valid inputs.
- The tool handles edge cases and errors gracefully.
- The system prompt includes the tool instructions.
- Any new config fields validate correctly.

---

## Adding a New Configuration Field

### Step 1: Add the Pydantic Model

In `config.py`, add the field to the appropriate model:

```python
class BusinessConfig(BaseModel):
    # ... existing fields ...
    new_field: str = "default_value"  # With default
    required_field: str               # Without default (required)
```

For complex structures, create a new model:

```python
class NewFeatureConfig(BaseModel):
    enabled: bool = False
    setting_a: str = "default"
    setting_b: int = 10

class BusinessConfig(BaseModel):
    # ... existing fields ...
    new_feature: NewFeatureConfig = NewFeatureConfig()
```

### Step 2: Update the YAML Example

Add the field to `config/businesses/example-dental.yaml`:

```yaml
# ... existing config ...

new_feature:
  enabled: true
  setting_a: "custom_value"
  setting_b: 20
```

### Step 3: Use the Field

Reference the new field wherever it is needed (agent.py, prompts.py, etc.):

```python
if config.new_feature.enabled:
    # Use the new configuration
    pass
```

### Step 4: Write Tests

In `tests/test_config.py`, add tests:

```python
def test_new_field_default():
    """New field uses default when not specified."""
    config = BusinessConfig.from_yaml_string(minimal_yaml)
    assert config.new_field == "default_value"

def test_new_field_custom():
    """New field accepts custom values."""
    config = BusinessConfig.from_yaml_string(yaml_with_custom_field)
    assert config.new_field == "custom_value"

def test_new_field_validation():
    """New field rejects invalid values."""
    with pytest.raises(ValidationError):
        BusinessConfig.from_yaml_string(yaml_with_invalid_field)
```

---

## Coding Standards

### Python Style

- Follow PEP 8 for code formatting.
- Use type hints for all function signatures and class attributes.
- Use docstrings for all public functions and classes.
- Maximum line length: 100 characters (soft limit).

### Naming Conventions

| Kind | Convention | Example |
|------|-----------|---------|
| Functions | `snake_case` | `load_business_config()` |
| Classes | `PascalCase` | `BusinessConfig` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_VOICE` |
| Variables | `snake_case` | `config_path` |
| Files | `snake_case` | `config.py` |
| Config slugs | `kebab-case` or `snake_case` | `example-dental` |

### Error Handling

- Validate inputs early (at config load time, not mid-call).
- Sanitize error messages before returning them to the LLM (no stack traces, no internal paths).
- Use `asyncio.to_thread()` for blocking I/O operations.
- Log errors with enough context for debugging.

### Security

- Always use `yaml.safe_load()` — never `yaml.load()`.
- Validate file paths and config slugs before use.
- Do not log sensitive data (API keys, caller phone numbers in production).
- Use Pydantic validation for all external input.

---

## Dependency Management

Dependencies are defined in `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
# ...
dependencies = [
    "livekit-agents",
    "livekit-plugins-openai",
    "livekit-plugins-noise-cancellation",
    "pydantic",
    "pyyaml",
    "python-dotenv",
]
```

### Adding a Dependency

1. Add the package to `dependencies` in `pyproject.toml`.
2. Reinstall: `pip install -e .`
3. Verify tests still pass: `python -m pytest tests/ -v`
4. Document why the dependency was added in your commit message.

### Dependency Philosophy

- Minimize dependencies. Each dependency is a maintenance burden and attack surface.
- Prefer well-maintained, widely-used packages.
- Pin major versions in `pyproject.toml` if a package has a history of breaking changes.

---

## Contributing

### Getting Started

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes.
4. Run all tests: `python -m pytest tests/ -v`
5. Commit with a descriptive message.
6. Push and open a pull request.

### Pull Request Guidelines

- **One feature per PR**. Keep pull requests focused and reviewable.
- **Include tests** for new functionality.
- **Update documentation** if your change affects user-facing behavior.
- **Describe the "why"** in your PR description, not just the "what."
- **All tests must pass** before merging.

### Commit Message Style

```
Add FAQ fallback behavior for unmatched questions

When lookup_faq finds no substring match, it now returns a message
that instructs the LLM to use its system prompt knowledge instead
of saying "I don't know."
```

- First line: imperative mood, under 72 characters.
- Blank line, then explanation of the change if needed.
- Focus on why the change was made, not just what changed.

### Areas for Contribution

The following areas are particularly welcome for contributions:

- **Webhook message delivery**: Implement the `_send_webhook()` function in `messages.py`.
- **Call recordings**: Integrate LiveKit Egress for call recording.
- **Email notifications**: Add email delivery method for messages.
- **New SIP trunk providers**: Add setup documentation for providers beyond Twilio/Telnyx.
- **Test coverage**: Add more edge case tests.
- **Performance profiling**: Identify and optimize latency bottlenecks.
- **Admin dashboard**: Web UI for managing configurations and viewing call history.

---

## Common Development Tasks

### Resetting the Message Directory

```bash
rm -rf messages/*.json
```

### Validating a Config File Without Starting the Agent

```python
# validate_config.py (one-off script)
from receptionist.config import load_config
import sys

try:
    config = load_config(sys.argv[1])
    print(f"Valid config for: {config.business.name}")
    print(f"  Type: {config.business.type}")
    print(f"  Timezone: {config.business.timezone}")
    print(f"  Voice: {config.voice.voice_id}")
    print(f"  FAQs: {len(config.faqs)}")
    print(f"  Routing entries: {len(config.routing)}")
except Exception as e:
    print(f"Invalid config: {e}")
    sys.exit(1)
```

```bash
python validate_config.py config/businesses/my-business.yaml
```

### Inspecting the Generated System Prompt

```python
# inspect_prompt.py (one-off script)
from receptionist.config import load_config
from receptionist.prompts import build_system_prompt
import sys

config = load_config(sys.argv[1])
prompt = build_system_prompt(config)
print(prompt)
print(f"\n--- Prompt length: {len(prompt)} characters ---")
```

```bash
python inspect_prompt.py config/businesses/example-dental.yaml
```

### Running Tests with Output

```bash
# Verbose output with print statements visible
python -m pytest tests/ -v -s
```
