---
name: "garmin-fitness"
description: "Read and analyze Garmin activity, training, health, sleep, and recovery data through the bundled read-only JSON CLI."
---

# Garmin fitness

Use the bundled `garmin-fetch` CLI as the only Garmin data boundary. Treat all returned fitness and health data as private.

## Set the project path

Resolve `PROJECT_DIR` to the directory that contains this `SKILL.md`. Run every command through the locked project:

```sh
uv run --project "$PROJECT_DIR" garmin-fetch ...
```

Do not call Garmin endpoints, import `garminconnect` in ad hoc code, or use a Claude Code or Strava intermediary.

## Authenticate

If a fetch returns `authentication_required`, tell the person to run this command privately in an interactive terminal:

```sh
uv run --project "$PROJECT_DIR" garmin-fetch auth login
```

Do not request, receive, log, or handle their Garmin password or MFA code. Ordinary fetches reuse saved tokens without prompting.

## Discover a method

Start from the user's fitness question, not from a memorized method name.

1. List the allowed read methods:

   ```sh
   uv run --project "$PROJECT_DIR" garmin-fetch methods
   ```

2. Select the narrowest method that fits the question.
3. Inspect its parameters:

   ```sh
   uv run --project "$PROJECT_DIR" garmin-fetch help METHOD
   ```

4. Build the smallest JSON object that satisfies the reported signature.

The CLI is the source of truth for the allowed surface. Do not maintain or infer a separate method catalog.

## Fetch data

Pass named parameters as one compact JSON object:

```sh
uv run --project "$PROJECT_DIR" garmin-fetch METHOD --params '{"parameter":"value"}'
```

Use live queries. Make only the calls needed to answer the question. For date ranges, start narrow and expand only when the analysis requires more data.

Never invoke a method that discovery doesn't list. Don't attempt mutations, low-level requests, GraphQL, binary downloads, retries, caching, or data uploads.

## Answer the question

Parse stdout as JSON. Synthesize the requested result rather than dumping the payload. State the dates and metrics used, distinguish Garmin-provided values from your calculations, and explain any missing data or failed calls.

Don't expose raw GPS traces, tokens, profile fields, or unrelated health data. Include only the private data needed for the person's answer.
