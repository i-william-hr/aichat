#!/usr/bin/env python3
"""aichat (Open WebUI) launcher with Monocle (monocle2ai) LLM tracing.

Sets up OTel/Monocle instrumentation before importing open_webui so the
openai / langchain clients it uses get wrapped as they load, then hands
over to the open-webui Typer CLI with all original argv (e.g.
`serve --host 127.0.0.1 --port [REDACTED:loopback-port]`).

Traces are written as JSON to [REDACTED:server-path] and
browsable at https://trace.inbox.li/ .
Disable at runtime with MONOCLE_TRACING=0 in the environment.
"""
import os
import sys

if os.environ.get("MONOCLE_TRACING", "1").strip().lower() not in ("0", "false", "off", ""):
    try:
        os.environ.setdefault("MONOCLE_TRACE_OUTPUT_PATH", "[REDACTED:server-path]")
        from monocle_apptrace import setup_monocle_telemetry
        setup_monocle_telemetry(workflow_name="aichat",
                                monocle_exporters_list="file")
    except Exception as exc:  # never let tracing break the chat app
        print(f"[aichat] monocle tracing unavailable: {exc}", file=sys.stderr)

from open_webui import app

sys.exit(app())
