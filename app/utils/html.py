"""Утилиты для безопасного рендеринга HTML."""
from html import escape as html_escape

def safe_html(text: str) -> str:
    """Экранирует специальные символы HTML для безопасного вывода."""
    return html_escape(str(text))