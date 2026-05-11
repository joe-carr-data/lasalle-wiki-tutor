"""
Configuration settings for the LaSalle catalog AI assistant.

Slimmed-down port of the original `lqc-ai-assistant-lib/config/settings.py`.
Keeps only what the single-agent skeleton needs:

- ProjectSettings (environment, assistant name, terminal logs flag)
- MongoSettings (connection + session collection)
- ReasoningMode presets (so the agent factory can take a mode name)

Drops: TeamSettings, ClassifierSettings, DealAgentSettings, RabbitMQSettings,
DatabricksLakeviewSettings — none of which apply to a single-agent app.

Settings load from environment variables / .env (pydantic-settings).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

# Load .env from the project root so OPENAI_API_KEY (and any other env
# vars consumed directly by libraries like Agno / OpenAI SDK) end up in
# os.environ. pydantic-settings reads its own declared fields directly
# from .env, but it does NOT export them to os.environ.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)


# ═══════════════════════════════════════════════════════════════════════════
# Reasoning Mode Types and Configurations (single-agent variant)
# ═══════════════════════════════════════════════════════════════════════════

ReasoningMode = Literal["instant", "thinking", "deep_thinking"]
ReasoningEffort = Literal["none", "low", "medium", "high"]
Verbosity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class AgentModelConfig:
    """Configuration for the assistant agent."""
    model: str
    reasoning_effort: ReasoningEffort
    verbosity: Verbosity
    reasoning_summary: str = "auto"


@dataclass(frozen=True)
class ReasoningModeConfig:
    """Reasoning preset for the assistant agent."""
    agent: AgentModelConfig


REASONING_MODES: dict[str, ReasoningModeConfig] = {
    "instant": ReasoningModeConfig(
        agent=AgentModelConfig(
            model="gpt-5.4",
            reasoning_effort="none",
            verbosity="low",
        ),
    ),
    "thinking": ReasoningModeConfig(
        agent=AgentModelConfig(
            model="gpt-5.4",
            reasoning_effort="medium",
            verbosity="medium",
        ),
    ),
    "deep_thinking": ReasoningModeConfig(
        agent=AgentModelConfig(
            model="gpt-5.4",
            reasoning_effort="high",
            verbosity="high",
        ),
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# Project + MongoDB settings (loaded from env / .env)
# ═══════════════════════════════════════════════════════════════════════════


class ProjectSettings(BaseSettings):
    """Project-level configuration."""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = Field(
        default="local",
        description="Environment: 'local' for dev (open CORS, /docs enabled), anything else for prod (locked-down)",
    )
    PUBLIC_HOST: str = Field(
        default="lasalle.generateeve.com",
        description="Public hostname this app is served from. Used for CORS allow-list and TrustedHostMiddleware in non-local environments.",
    )
    ASSISTANT_NAME: str = Field(
        default="LaSalle Wiki Tutor",
        description="Display name for the assistant",
    )
    TERMINAL_LOGS_ENABLED: bool = Field(
        default=False,
        description="Enable detailed terminal logs for event outputs (smart_renderer)",
    )


class MongoSettings(BaseSettings):
    """MongoDB connection + session persistence configuration."""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Local/Docker URL
    MONGO_URL: str = Field(
        default="mongodb://admin:password@localhost:27017",
        description="MongoDB connection URL (used when ENVIRONMENT='local')",
    )

    # MongoDB Atlas (production)
    MONGO_CLUSTER: str = Field(default="", description="MongoDB Atlas cluster URL")
    CLUSTER_APP_NAME: str = Field(default="", description="MongoDB application name")
    MONGO_DATABASE: str = Field(
        default="lasalle_catalog_assistant",
        description="Database name for sessions and event store",
    )
    MONGO_RW_USERNAME: str = Field(default="", description="MongoDB username")
    MONGO_RW_PASSWORD: str = Field(default="", description="MongoDB password")

    # Collections
    AGNO_STORAGE_COLLECTION: str = Field(
        default="agno_storage",
        description="Collection for Agno session persistence",
    )
    EVENT_STORE_COLLECTION: str = Field(
        default="agent_events",
        description="Collection for the event store",
    )

    # Connection pool
    MAX_POOL_SIZE: int = Field(default=60)
    MIN_POOL_SIZE: int = Field(default=10)
    SOCKET_TIMEOUT_MS: int = Field(default=5000)
    CONNECT_TIMEOUT_MS: int = Field(default=2000)
    WAIT_QUEUE_TIMEOUT_MS: int = Field(default=1000)


# Singleton instances
PROJECT_SETTINGS = ProjectSettings()
MONGO_SETTINGS = MongoSettings()


__all__ = [
    "AgentModelConfig",
    "MONGO_SETTINGS",
    "MongoSettings",
    "PROJECT_SETTINGS",
    "ProjectSettings",
    "REASONING_MODES",
    "ReasoningEffort",
    "ReasoningMode",
    "ReasoningModeConfig",
    "Verbosity",
]
