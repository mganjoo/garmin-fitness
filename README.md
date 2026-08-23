# garmin-fitness

`garmin-fitness` is a thin, read-only JSON command-line interface (CLI) for the
structured fetch methods in [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect).
It is bundled with an Agents skill so an agent can discover the supported
Garmin methods at run time instead of relying on a copied method catalog.

This project uses an unofficial Garmin Connect API. Garmin can change or
disable that API without notice, and a request that works with one account or
device might not work with another. This project isn't affiliated with or
endorsed by Garmin.

## Read-only boundary

The CLI exposes only structured reads that the project has explicitly
reviewed. The pinned `garminconnect.Garmin` public callable surface is divided
into an allowlist and a denied-method ledger. The policy audit fails closed if
a dependency update adds, removes, or duplicates a callable, or leaves one in
both classifications.

The denied set includes remote mutations, authentication methods, low-level
request helpers, arbitrary GraphQL, and binary downloads. A denied or unknown
method fails locally before the CLI creates an authenticated client. The
boundary does not make the unofficial API stable, and it doesn't reduce the
sensitivity of data returned by an allowed read.

## Install the CLI

You need Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

From the repository root, install the locked project and development
dependencies:

```sh
uv sync --frozen
```

Run the CLI through `uv`:

```sh
uv run garmin-fetch methods
```

Every successful command writes compact JSON to standard output. Errors use a
stable JSON object on standard error and a nonzero exit code. The CLI doesn't
provide a pretty-print mode, transformations, caching, or retries.

## Discover and fetch data

Use discovery before you fetch data. Discovery doesn't authenticate or contact
Garmin.

1. List the allowed methods:

   ```sh
   uv run garmin-fetch methods
   ```

2. Inspect a method's signature and upstream docstring:

   ```sh
   uv run garmin-fetch help get_activities
   ```

3. Pass all method arguments as one JSON object of named parameters:

   ```sh
   uv run garmin-fetch get_activities --params '{"start":0,"limit":1}'
   ```

The CLI rejects malformed JSON, unknown parameter names, missing required
parameters, and values that aren't URL-safe scalars before
authentication. Method results pass through without domain transformations and
must be JSON serializable.

## Authenticate privately

Run the interactive login in a private terminal:

```sh
uv run garmin-fetch auth login
```

Enter your Garmin email, password, and multifactor authentication (MFA) code
only at the prompts. Don't put credentials in command arguments, paste them
into an agent conversation, or run login while recording or sharing the
terminal.

The authentication boundary stores OAuth tokens, not your email or password,
under `~/.garminconnect`. It restricts the token directory and token files to
the local account. Later status and fetch commands load the saved tokens,
let the underlying client refresh them, and save the refreshed tokens without
prompting:

```sh
uv run garmin-fetch auth status
```

If saved tokens are missing, expired, or rejected, the command returns the
`authentication_required` JSON error. Run `auth login` privately again. Never
commit, copy, or share the token store.

## Run a private smoke test

Use a local terminal that isn't recorded, shared, or captured by a command
transcript. Live results can contain health information, location history, and
account details.

1. Run `methods` and `help` for the read that you plan to test.
2. Run `auth login` privately if `auth status` reports
   `authentication_required`.
3. Run `auth status` in a second process to confirm that saved tokens work
   without another prompt. Inspect the result only in the terminal.
4. Choose representative allowed reads for the profile, activity, training,
   and recovery categories. Use `help` to construct each `--params` object.
5. Run each fetch directly in the terminal. Don't redirect, pipe, copy, or
   paste the JSON output into logs, issues, commits, or agent conversations.
6. Request a denied method with inert parameters to confirm that the local
   policy rejects it before authentication:

   ```sh
   uv run garmin-fetch delete_activity --params '{}'
   ```

Record only whether each category succeeded and the stable error code for any
failure. Don't record response payloads, credentials, tokens, activity routes,
or health values.

## Develop and verify

Run the same locked checks as CI from the repository root:

```sh
uv sync --frozen
uv run ruff check .
uv run mypy
uv run pytest
```

CI doesn't use Garmin credentials and doesn't make live Garmin requests. All
automated tests use fakes. For dependency changes, follow
[the dependency upgrade procedure](CONTRIBUTING.md#upgrade-a-dependency).

## License

This project is available under the [MIT License](LICENSE).
