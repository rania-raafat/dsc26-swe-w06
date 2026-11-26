# AI usage

## Tools

- **ChatGPT:** Used to understand the task requirements, discuss the implementation of the budget and streaming logic, review edge cases, and debug the FastAPI SSE endpoint.
- **VS Code:** Used to edit and review the project files.
- **Windows CMD:** Used to run the application commands and execute the test suite with `pytest -q`.
- **FastAPI documentation and source code:** Used to verify the correct Server-Sent Events response behavior in FastAPI 0.141.1.

## What AI got wrong

The first suggested SSE implementation returned an `EventSourceResponse` manually and assumed it would encode the `ServerSentEvent` objects automatically. I checked the FastAPI 0.141.1 documentation and source code, found that SSE encoding is handled by the FastAPI routing layer when using `response_class=EventSourceResponse`, and changed the endpoint to yield `ServerSentEvent` objects directly.

Another issue was that the initial budget settlement logic calculated input cost even when a provider failed before producing its first token. I noticed this by comparing the implementation with the requirement that pre-first-token failures must settle at zero cost, and corrected the settlement logic.

## In my own words

1. Why is it safe to switch provider before the first token and not after?

   Before the first token, no response has been sent to the client, so we can safely discard the failed provider and try another one. After sending the first token, switching providers could mix two different responses and produce an inconsistent explanation.

2. Which checks did you put before the stream starts, and why could they not be error events instead?

   I validate the request body and tenant ID, build the prompt, and check whether the tenant can afford the cheapest provider's estimated cost. These checks must happen before the response starts because HTTP status codes such as 422 and 429 need to be returned before the server commits to a 200 streaming response; after streaming starts, errors must be sent as SSE events.