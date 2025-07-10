# Cappuccino

This repository contains asynchronous tools for the Cappuccino agent and a small test suite.

## Running Tests

Install dependencies and run the tests using `pytest`:

```bash
pip install -r requirements.txt
pytest -q
```

## Continuous Integration

A GitHub Actions workflow installs the dependencies defined in `requirements.txt` and runs the test suite on every push and pull request. API keys such as `OPENAI_API_KEY` and `SEARCH_API_KEY` are provided to the workflow via repository secrets so no sensitive values are committed to the repository.
