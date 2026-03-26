"""
FishMindOS interaction package.
"""

from fishmindos.interaction.channels import Spinner, TerminalChannel, TerminalUI
from fishmindos.interaction.manager import InteractionManager, create_interaction_manager

__all__ = [
    "InteractionManager",
    "TerminalChannel",
    "TerminalUI",
    "Spinner",
    "create_interaction_manager",
]
