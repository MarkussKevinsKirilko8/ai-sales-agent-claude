import re


def markdown_to_telegram_html(text: str) -> str:
    """Convert Claude's markdown output to Telegram-compatible HTML."""
    # Headers → bold
    text = re.sub(r"^### (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold: **text** → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *text* → <i>text</i>
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)

    # Inline code: `text` → <code>text</code>
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)

    # Escape any remaining HTML special chars that aren't our tags
    # (do this carefully to not break our <b>, <i>, <code> tags)

    return text.strip()
