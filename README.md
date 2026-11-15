# aichat

A login-protected AI chat for end users, built on [Open WebUI](https://github.com/open-webui/open-webui).

The point of the setup is the access model: **end users see exactly one model**,
and an administrator can switch which one at any time, without touching anyone's
configuration. Admins see every model from every configured provider.

## How model access control works

Visibility is enforced by access grants, not merely by hiding entries in the UI:

- A model with **no grants** is visible to **administrators only**
- A model granted `user:* read` is visible to **everyone**
- Administrators see all models from all configured connections by default

So "give everyone the new model, take the old one away" is: grant the new one to
the wildcard user, then clear the old one's grants. Clearing the grants is what
returns it to admin-only — there is no separate "unpublish" flag.

The same thing is available in the UI under Workspace → Models → a model →
Visibility/Access.

## Accounts

- One **administrator**, created on first run; its credentials are kept in a
  `0600` file beside the application
- **Signup is closed.** The first user becomes the administrator; after that,
  only administrators can create accounts
- Additional users are created in the admin panel (or with the `owui-admin`
  CLI, below)

## Providers

Any OpenAI-compatible endpoint works — the provider connection is just a base
URL and a key, and several can be active at once, with the administrator's model
list merging them.

## Stack

Open WebUI, started through a traced launcher. Data — SQLite plus uploads —
lives in a `data/` directory beside the application. A thin launcher
(`trace_launcher.py`) wraps the standard entrypoint to install
OpenTelemetry/monocle tracing before the app imports. Tracing is optional and
can never break the chat app.

The virtualenv is deliberately on an **older Python** (3.11) than the system
one. That is not neglect: the pinned Open WebUI release supports 3.11, and the
venv pins the version the app actually supports.

**Torch is installed CPU-only, on purpose.** On a machine with no GPU, the
default PyPI torch wheel pulls in roughly 5.3 GB of NVIDIA CUDA libraries and
triton that can never execute. `requirements.txt` records the exact install and
cleanup commands. Nothing in the running service loads them: Open WebUI only
imports torch lazily, on the RAG and embedding paths, and even then the CPU
build is what it ends up using.

## Installation

```bash
git clone <repo-url> aichat
cd aichat

# Use a Python the pinned Open WebUI supports (3.11 is known good)
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt

# On a GPU-less machine, swap the transitive CUDA torch for the CPU build and
# drop the NVIDIA libraries it pulled in (exact commands also documented at
# the top of requirements.txt):
uv pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.0+cpu'
uv pip uninstall nvidia-cublas nvidia-cuda-cupti nvidia-cuda-nvrtc \
    nvidia-cuda-runtime nvidia-cudnn-cu13 nvidia-cufft nvidia-cufile \
    nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-cusparselt-cu13 \
    nvidia-nccl-cu13 nvidia-nvjitlink nvidia-nvshmem-cu13 nvidia-nvtx triton

# Secrets stay out of git — mode 0600, beside the application:
#   aichat.env            — read by the service manager before privileges drop
#   .webui_secret_key     — session signing key
#   admin-credentials.txt — first-run admin credentials
```

## Running it

```bash
./venv/bin/python trace_launcher.py serve --host 127.0.0.1 --port [REDACTED:loopback-port]
```

The launcher is a thin wrapper that starts tracing and then hands off to the
standard Open WebUI entrypoint. The app binds loopback only; put a reverse
proxy (nginx or similar) in front for TLS.

Example systemd unit:

```ini
[Unit]
Description=aichat Open WebUI (LLM chat frontend)
After=network.target

[Service]
Type=simple
User=aichat
Group=aichat
WorkingDirectory=/opt/aichat
Environment=DATA_DIR=/opt/aichat/data
EnvironmentFile=/opt/aichat/aichat.env
# Open WebUI caches things under $HOME on first run; accounts without one
# need a writable HOME.
Environment=HOME=/tmp
ExecStart=/opt/aichat/venv/bin/python /opt/aichat/trace_launcher.py serve --host 127.0.0.1 --port [REDACTED:loopback-port]
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Configuration

An environment file, mode `0600`, read by the service manager before privileges
drop:

- `WEBUI_SECRET_KEY` — the session signing key
- `WEBUI_AUTH_COOKIE_SECURE` — cookie security flag (true in production; see
  "Things worth knowing")
- `DATA_DIR` — where the SQLite database, vector store and uploads live
- `MONOCLE_TRACING` / `MONOCLE_TRACE_OUTPUT_PATH` — tracing on/off and its
  output directory; tracing failures are logged and swallowed

## Admin CLI

`owui-admin` is a command-line admin client for the instance. It talks to the
app over its own HTTP API rather than poking the SQLite file, so it goes
through the same validation and permission filtering the admin UI does, and it
keeps working while the database is being written. Credentials come from
`OWUI_ADMIN_EMAIL` / `OWUI_ADMIN_PASSWORD`, from the `0600`
`admin-credentials.txt` beside the script, or from a prompt; the JWT is cached
in `/tmp`.

```bash
./owui-admin users list
./owui-admin users add someone@example.com "Someone" 'initial-password'
./owui-admin password someone@example.com 'new-password'   # account recovery
./owui-admin models                    # models and who can use each
./owui-admin grants set grok-4.6 'user:*'   # make a model public
./owui-admin grants clear grok-4.6          # back to admin-only
```

## Model access control is data, not code

The "end users see exactly one model" restriction described above is **not** a
patch to the installed package. It is a single row in the `access_grant` table
of `data/webui.db`:

    model | grok-4.6 | user | * | read

A model with no grants is administrator-only, so removing that row is what takes
a model away from everyone. Because this lives in the database rather than in
`site-packages`, **it survives package upgrades untouched.** There is no local
patch to reapply when Open WebUI is updated, and no `.py` file under
`open_webui/` is modified.

The one thing that *is* edited inside `site-packages` is
`open_webui/static/` — but only incidentally, because Open WebUI rewrites its
own branding defaults there on first run. Keeping the venv read-only makes
those writes fail harmlessly; the branding of record is served by the reverse
proxy from a static directory and does not come from `site-packages` at all.

## Things worth knowing

**It is served at the root of its hostname.** Open WebUI's frontend hardcodes
its base path at build time, so it cannot live under a subpath. Use a dedicated
hostname rather than a `/chat/` prefix, and know that before planning a
migration that would want one.

**Signup being closed is the only thing limiting who gets an account.** With
signup off, account creation is an administrative act — which is correct. Do not
turn it on to make onboarding easier; that converts an invite-only service into
an open one, and every account can spend provider quota.

**The session cookie's Secure flag depends on configuration.** If it is set to
false while the site is served over HTTPS, session cookies are not marked Secure
and can travel over plaintext. That should not be the production setting.

**The admin password is in a plaintext file on disk.** That is the usual
Open WebUI arrangement, and it is a credential in a file that has to be readable
by the operator. Restrict it, and rotate it if the file has ever been readable by
anyone else.

**An administrator can see every conversation.** That is inherent to a
single-tenant deployment with one admin account. If several people of differing
trust will use it, that is the thing to design around.

**WebSocket support is required** for live updates and works through the reverse
proxy. If chat appears to hang after a message, check the proxy's upgrade
headers before debugging the app.

## License

MIT — see [LICENSE](LICENSE).
