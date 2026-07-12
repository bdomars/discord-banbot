from typing import TypedDict


class AttachmentSummary(TypedDict):
    filename: str
    url: str


class RecentPostEvent(TypedDict):
    timestamp: float
    created_at: str
    guild_id: int
    guild_name: str
    channel_id: int
    channel_name: str
    message_id: int
    content: str
    attachments: list[AttachmentSummary]
