# Recordings

Genuine recorded exchanges with Gemini, one JSON file per call, committed so
the demo runs offline with no credentials.

Each file holds the rendered prompt alongside the response, so you can read
exactly what the model was asked — including the fenced untrusted block — and
check for yourself that the injection payloads were present and were treated
as data.

The filename is a hash of the rendered prompt. Any change to a prompt file, to
the fixture, or to the brief therefore produces a miss rather than silently
replaying a recording whose inputs have moved. To regenerate:

```bash
uv sync --all-extras
export GEMINI_API_KEY=...
uv run ci run --record
```
