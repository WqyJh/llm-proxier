# Python Engineering AGENTS.md file

## Core design philosophy for building robust and maintainable project.

- **Embrace Strategic Programming**:
    - **Design First**: Your primary goal is to "create a great design." Making the code work is a natural outcome of this process.
    - **Continuous Improvement**: Every code change is an opportunity to improve the system's design. The codebase should be cleaner *after* your commit.
    - **Technical Debt Registry**: Any tactical compromise (tech debt) requires approval from the Tech Lead and must be marked in the code (`# TODO(tech-debt): [Reason] by [Name] on [YYYY-MM-DD]`) and ticketed immediately.

- **Mandate Upfront Collaborative Design**:
    - Never start coding without a detailed plan and implementation specifics that have been thoroughly discussed with the user.
    - Proactively ask questions to resolve all ambiguities and avoid making assumptions.
    - Only begin implementation when the plan is completely clear. The design phase should be so thorough that no further user interaction is needed once coding begins.

- **Build "Deep Modules"**:
    - A module's interface must be extremely simple, while its internal implementation can be powerful.
    - **Example**: An Agent's skill module should expose a single `execute(task: Task)` method, hiding the complexity of LLM calls, parsing, and tool usage internally.

- **Enforce Radical Information Hiding**:
    - A single design decision or piece of knowledge (e.g., a specific DB schema, a third-party API key) must be encapsulated within **one and only one** module.

- **Maintain Abstraction Across Layers**:
    - Each layer in the architecture (e.g., API -> Service -> Agent) must provide a distinctly higher-level abstraction than the one below it.
    - Prohibit meaningless "pass-through" methods that simply delegate calls without adding value.

- **Pull Complexity Downwards**:
    - As the author of a module, it is your responsibility to make the caller's life easy, even if it means more work for you. A simple interface is more important than a simple implementation.

- **"Define Errors Out of Existence"**:
    - Prefer to redefine API behavior to avoid exceptions.
    - **Example**: A request to delete an object that doesn't exist should succeed silently, not throw a `NotFound` error.
    - When exceptions are unavoidable, define specific, self-describing custom exception classes that inherit from a common `BaseAppException`.

- **Design It Twice**:
    - For any significant design decision (a new class, feature, or refactoring), create at least two alternative designs before writing implementation code.
    - This practice forces a deeper consideration of the problem and its trade-offs.
    - Compare the alternatives; the final design will often be a superior hybrid of the initial ideas. This small upfront investment prevents costly redesigns later.

- **Prefer Standard Libraries and Well-Validated Packages**:
    - If there is a standard, widely-adopted, and well-validated package that implements the required functionality, prioritize using it over custom implementations. Official package is preferred.
    - **Example**: Use `pydantic V2` for data validation, `requests` for HTTP clients, etc.
    - Only build custom solutions when no suitable standard library or package exists, or when the existing solutions don't meet specific requirements.
    - This principle reduces maintenance burden, improves reliability, and leverages community-tested solutions.

- **Requirements on Documentations**:
    - Don't add any kind of additional documentations (like README.md, SUMMARY.md, etc) in a separate file unless required. Documentations should always be accompanied with code.

## Debugging
- It is preferred to use an isolated minimal reproduction python file to find and fix bugs.
- If the data flow and control flow are too complex to reproduce using a simple file, feel free to add print statements inside the code that you are debugging. When the bug is fixed, remove print statements.
- Use uv to run the project scripts: `uv run llm-proxier`
- For running specific test files: `uv run python tests/test_main.py`
- When starting the backend project, terminal will be blocked and won't respond, open a new terminal for other operations.

## Mandatory coding standards, tooling, and practices for all Python projects.
- **Use Comment-Driven Design**:
  - **Write Comments First**: Write the interface comment (docstring) and type annotations (including parameters and returns, including None) for a function or class *before* writing its implementation.
  - **Validate Design with Comments**: If a function's purpose is hard to explain in a simple docstring, the abstraction is too complex. Stop and redesign it.
  - **Comments Explain "Why"**: Code shows "how." Comments must explain what the code cannot: the intent, design trade-offs, and contract (`why`, not `what`).

- **Use Precise and Consistent Naming**:
  - Names must create an accurate mental model. Avoid generic terms like `data`, `info`, `temp`.
  - A single concept must have the same name across the entire project.

- **Enforce Type Safety and Data Contracts**:
  - **Mandatory Type Annotations**: All function signatures (arguments and returns) and key class variables **must** have type hints.
  - **Pydantic for Data Contracts**: All external data structures (API request/response bodies, configs, DB records) **must** be defined using Pydantic V2 models for both static analysis and runtime validation.
  - **Protocols for Interfaces**: Use `typing.Protocol` to define shared behavior interfaces, favoring composition over rigid class inheritance.
  - **Interface Location**: Define interfaces in the same file as their main implementation to maintain cohesion and reduce file navigation.
  - **Pydantic for Configuration**: **Must** use Pydantic V2 to manage application configuration and secrets. This provides auto-loading, type validation, and IDE support.

- **Implement Formatted Logging**:
  - **Standard**: Use the built-in `logging` module. Never use root logging. Always use module-level logging and print module names. Always record time up to seconds and ask user for a proper time zone.
  - **Log Levels**:
    - `INFO`: For key business process milestones (e.g., "Request received", "Agent task started").
    - `WARNING`: For recoverable, non-breaking issues (e.g., "Third-party API latency spike").
    - `ERROR`: For failures that broke the current operation and require intervention.

- **Adhere to the Mandatory Toolchain**:
  - **Single Source of Truth**: `pyproject.toml` is the definitive source for project metadata, dependencies, and tool configuration.
  - **Dependency Management**: Use `uv` for all package and virtual environment management. Ensure reproducible environments with `uv sync` and `uv.lock`.
  - **Code Quality**: `ruff` is the **only** standard for linting and formatting. Its rules in `pyproject.toml` are the "code law."
  - **Commit Gateway**: `pre-commit` **must** be configured to run all quality checks (Ruff, Mypy) before a commit can be created.

## Specific Python code style rules for type safety, interfaces, and logging.

- **Enforce Comprehensive Type Annotations**:
  - All function signatures (arguments and return values, including None) and key class variables **must** be fully type-annotated. This is not optional.
  - This practice enables static analysis, improves code clarity, and is enforced by `Mypy` and `Ruff` during pre-commit checks.
  - **Example**:
    ```python
    # Bad: Ambiguous and unsafe
    def process_user(user, data):
        # ...
        return {"status": "ok"}

    # Good: Explicit, self-documenting, and statically checkable
    from .models import User, UserStatus

    def process_user(user: User, data: dict) -> UserStatus:
        # ...
        return UserStatus(status="ok")
    ```

- **Define Interfaces with `typing.Protocol` Only When Inheritance is Needed**:
  - Only use `typing.Protocol` when you need to define a base class or abstract class that will be inherited from or implemented by other classes.
  - For simple interfaces that don't require inheritance, use regular classes, type hints or Pydantic V2 models instead.
  - This approach achieves loose coupling and supports dependency injection while avoiding unnecessary complexity for simple cases.
  - **Example for Inheritance Cases**:
    ```python
    from typing import Protocol, Any

    class Cacheable(Protocol):
        """Defines an interface for any object that can be cached."""
        def get_cache_key(self) -> str:
            ...
        def to_cache_dict(self) -> dict[str, Any]:
            ...

    # Good: This function depends on the protocol, not a specific class.
    # It can now accept any object that implements Cacheable.
    def add_to_cache(item: Cacheable, cache_client: CacheClient):
        key = item.get_cache_key()
        data = item.to_cache_dict()
        cache_client.set(key, data)
    ```
  - **Example for Simple Cases (No Inheritance Needed)**:
    ```python
    from typing import TypedDict

    class UserData(TypedDict):
        """Simple data structure, no inheritance needed."""
        id: int
        name: str
        email: str

    def process_user(user_data: UserData) -> None:
        # Process user data without needing protocol inheritance
        pass
    ```

- **Use `%`-style Formatting in Logging Statements**:
  - You **must** use lazy, `%`-style formatting when passing arguments to log messages.
  - **Do not** use f-strings (`f"..."`) or `.format()` for logging. These methods format the string *before* the logging call, incurring performance costs even if the log level prevents the message from being shown. The `%`-style defers string formatting until it's certain the message will be emitted.
  - **Example**:
    ```python
    import logging
    from .utils import get_expensive_debug_info

    # Bad: The f-string and get_expensive_debug_info() are ALWAYS evaluated.
    logging.debug(f"User {user.id} transaction failed with payload: {get_expensive_debug_info(payload)}")

    # Good: Arguments are only evaluated if the log level is DEBUG or lower.
    logging.debug("User %s transaction failed with payload: %s", user.id, get_expensive_debug_info(payload))
    ```
