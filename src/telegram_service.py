"""Telegram Bot API integration."""

from decimal import Decimal, InvalidOperation

import requests
from requests import RequestException


def format_danish_currency(value: str) -> str:
    """Format a decimal value with Danish thousands and decimal separators."""
    normalized = value.strip().replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", ".")

    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        raise ValueError(f"Ugyldigt beløb fra Partner-ads: {value}") from None

    return f"{amount:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def build_sale_message(sale: dict[str, str]) -> str:
    """Build the Telegram message for one Partner-ads sale."""
    required_fields = (
        "program",
        "dato",
        "tidspunkt",
        "omsaetning",
        "provision",
        "url",
    )
    missing = [field for field in required_fields if not sale.get(field)]
    if missing:
        raise ValueError(
            f"Salget mangler nødvendige felter: {', '.join(missing)}."
        )

    revenue = format_danish_currency(sale["omsaetning"])
    commission = format_danish_currency(sale["provision"])
    return (
        "Nyt salg\n\n"
        "Program\n"
        f"{sale['program']}\n\n"
        "Dato\n"
        f"{sale['dato']}\n\n"
        "Tidspunkt\n"
        f"{sale['tidspunkt']}\n\n"
        "Omsætning\n"
        f"{revenue} kr.\n\n"
        "Provision\n"
        f"{commission} kr.\n\n"
        "Website\n"
        f"{sale['url']}"
    )


class TelegramService:
    """Send messages through the Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN og TELEGRAM_CHAT_ID skal angives i .env."
            )

        self.bot_token = bot_token
        self.chat_id = chat_id

    def send_message(self, message: str) -> None:
        """Send a text message to the configured Telegram chat."""
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message},
                timeout=10,
            )
            response.raise_for_status()
        except RequestException as error:
            description = "Ukendt fejl fra Telegram."
            if error.response is not None:
                try:
                    description = error.response.json().get("description", description)
                except ValueError:
                    pass

            raise RuntimeError(
                f"Telegram-beskeden kunne ikke sendes: {description}"
            ) from None

    def send_sale(self, sale: dict[str, str]) -> None:
        """Send a message for the supplied Partner-ads sale."""
        self.send_message(build_sale_message(sale))
