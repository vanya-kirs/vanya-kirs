class BannedError(Exception):
    """Raised when Telegram returns UserDeactivatedBanError. Stops all retries."""
