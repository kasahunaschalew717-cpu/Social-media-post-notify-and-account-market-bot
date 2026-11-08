import enum


class SubscribeState(int, enum.Enum):
    SELECT_PLATFORM = 1
    ENTER_HANDLE = 2


class SellState(int, enum.Enum):
    SELECT_PLATFORM = 10
    ENTER_HANDLE = 11
    ENTER_PRICE = 12
    ENTER_FOLLOWERS = 13
    ENTER_NICHE = 14
    ENTER_DESCRIPTION = 15
    VERIFY_CHALLENGE = 16


class EscrowState(int, enum.Enum):
    SUBMIT_CREDENTIALS = 20
    ENTER_DISPUTE_REASON = 21
    SUBMIT_RATING = 22


class AdminState(int, enum.Enum):
    SELECT_DISPUTE = 30
    ENTER_RESOLUTION_NOTE = 31

