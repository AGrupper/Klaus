# Coding Standards & Architecture Rules

## 1. Core Philosophy: Clarity Over Cleverness
The codebase must be highly readable and easy to maintain. Avoid overly complex "Pythonic" tricks (like deep list comprehensions, complex decorators, or obscure lambda functions). Write code that relies on fundamental Computer Science concepts. 

## 2. Object-Oriented Principles
* Since the system will have multiple tools and connections, utilize standard Object-Oriented Programming (OOP). 
* Use clear Classes for external integrations (e.g., `class GoogleCalendarManager:`, `class RosterStore:`). 
* This mirrors standard practices taught in C# and foundational Python, keeping the architecture organized and predictable.

## 3. Naming Conventions
* **Variables & Functions:** `snake_case` (e.g., `fetch_unread_emails`). Be highly descriptive. `user_calendar_events` is better than `events`.
* **Classes:** `PascalCase` (e.g., `TelegramBotListener`).
* **Constants:** `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES = 3`).

## 4. Documentation and Commenting
* **Docstrings:** Every class and function must have a brief docstring explaining its purpose, arguments, and return types.
* **Inline Comments:** Use heavy inline commenting for any logic that handles API requests, database queries, or OAuth token refreshes. Explain *why* a block of code exists, not just *what* it does.

## 5. Error Handling & Modularity
* Never use bare `except:` blocks. Always catch specific exceptions (e.g., `except requests.exceptions.Timeout:`).
* If an API call fails, the code must gracefully log the error and return a clear message to the agent, rather than crashing the application.
* Keep tools strictly modular. The `gmail_tool.py` should not contain any logic for TickTick tasks.