"""
Vibe Viewer - Web viewer for Mistral Vibe CLI conversations

A clean Python package that provides a web interface to view your
Mistral Vibe CLI conversation history in a browser.
"""

__version__ = "0.2.0"
__author__ = "Jakob"
__description__ = "Web viewer for Mistral Vibe CLI conversations"

from .__main__ import main, SessionManager, VibeSession

__all__ = ["main", "SessionManager", "VibeSession", "__version__"]
