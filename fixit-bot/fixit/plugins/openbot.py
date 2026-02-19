"""OpenBot plugin — teach the crow about the OpenBot/OpenClaw stack."""

from __future__ import annotations

from fixit.plugins.base import Plugin, ContextHint
from fixit.signals import FileSystemSignal, ProcessSignal, HttpSignal, EnvVarsSignal, GitSignal


class OpenBotPlugin(Plugin):
    """OpenBot + OpenClaw stack awareness."""

    name = "openbot"
    version = "0.1.0"

    def signals(self):
        return [
            FileSystemSignal("/root/.openclaw/", watch=["*.json", "*.md"]),
            FileSystemSignal("/tmp/openclaw/sessions/", watch=["*"]),
            ProcessSignal("openclaw-gateway"),
            HttpSignal("http://localhost:18789/", timeout=10),
            EnvVarsSignal(watch=["*_API_KEY", "OPENCLAW_*", "MOONSHOT_*"]),
            GitSignal("/opt/openbot"),
        ]

    def context(self):
        return [
            ContextHint("Session files in /tmp/openclaw/sessions/ grow without bounds"),
            ContextHint("Gateway takes ~50s to start after systemctl restart"),
            ContextHint("ANTHROPIC_API_KEY in shell env causes provider auto-discovery — should only be in openclaw.json"),
            ContextHint("Config at /root/.openclaw/openclaw.json must be writable or gateway crashes with EPERM"),
            ContextHint("Model chain: Kimi K2.5 (executive) → Claude Opus 4.6 (code workers) → GPT-4o-mini (ops)"),
            ContextHint("t3.medium has 4GB RAM — gateway ~1.2GB, headroom is tight with browser sidecar"),
            ContextHint("All work goes to DNA repo (quarantine) — never touch production (BetApp)"),
            ContextHint("MOONSHOT_API_KEY for Kimi, OPENAI_API_KEY for GPT, ANTHROPIC_API_KEY for Claude"),
            ContextHint("Web search enabled via Kimi $web_search (server-side, zero EC2 impact)"),
            ContextHint("Memory system at /root/.openclaw/memory/ — MEMORY.md is SPOF if not backed up"),
        ]
