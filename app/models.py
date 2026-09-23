from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MediaInfo(BaseModel):
    kind: Literal["photo", "video", "audio", "file", "other"]
    name: str | None = None
    size: int | None = None
    mime_type: str | None = None
    playable: bool = False
    downloadable: bool = True


class Dialog(BaseModel):
    chat_id: int
    title: str
    dialog_type: str
    username: str | None = None
    unread_count: int = 0
    pinned: bool = False
    archived: bool = False
    last_message_id: int | None = None
    last_message_at: datetime | None = None


class ChatInfo(BaseModel):
    chat_id: int
    title: str
    dialog_type: str
    username: str | None = None
    participants_count: int | None = None
    status: str | None = None
    is_bot: bool = False
    verified: bool = False
    scam: bool = False
    fake: bool = False
    photo_available: bool = False


class Message(BaseModel):
    chat_id: int
    message_id: int
    text: str = ""
    date: datetime
    sender_id: int | None = None
    sender_name: str | None = None
    outgoing: bool = False
    edited: bool = False
    reply_to_message_id: int | None = None
    media: MediaInfo | None = None
    deleted: bool = False


class ClientStatus(BaseModel):
    configured: bool = False
    connected: bool = False
    authorized: bool = False
    state: Literal[
        "UNCONFIGURED",
        "IMPORT_READY",
        "CONNECTING",
        "CONNECTED",
        "AUTH_REQUIRED",
        "PROXY_ERROR",
        "STOPPED",
    ] = "UNCONFIGURED"
    user_id: int | None = None
    display_name: str | None = None
    active_route: str | None = None
    source_session_available: bool = False
    client_session_exists: bool = False
    last_error: str | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    reply_to_message_id: int | None = Field(default=None, ge=1)


class EditMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ForwardMessageRequest(BaseModel):
    target_chat_id: int


class LoginPhoneRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=20)


class LoginCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class LoginPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class DesktopError(Exception):
    """Safe application error intended for the local API."""
