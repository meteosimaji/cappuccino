# Cappuccino

Cappuccino aims to be a general‑purpose AI assistant. The project follows the design guidelines in `AGENTS.md` which emphasize high quality code, modular architecture and robust asynchronous tooling. Tools are intended to run concurrently and the API is exposed through FastAPI for easy humanoid integration.

## Setup
1. Create a Python environment (Python 3.12 or later recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and add your API keys.

## Running the server
Start the FastAPI server with:
```bash
uvicorn main:app --reload
```
This runs the minimal API defined in `main.py`.

## Testing
Execute unit tests using `pytest`:
```bash
pytest -q
```

## Design philosophy
Key principles from `AGENTS.md`:
- Produce readable and maintainable Python code with proper error handling and testing【F:AGENTS.md†L80-L95】.
- Expose the agent core through a high-performance asynchronous API using FastAPI and WebSockets【F:AGENTS.md†L1760-L1776】.
- Ensure state management, sandbox awareness and parallel execution where appropriate【F:AGENTS.md†L1840-L1848】.