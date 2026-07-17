"""Shared placeholder page renderer."""

from dashboard.components.ui import render_placeholder


def show(title: str) -> None:
    render_placeholder(title)
