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


class RecentMediaItem(BaseModel):
    media_id: str
    kind: Literal["sticker", "gif"]
    label: str
    mime_type: str | None = None


class ReactionSummary(BaseModel):
    emoji: str
    count: int = Field(ge=1)
    chosen: bool = False


class Dialog(BaseModel):
    chat_id: int
    title: str
    dialog_type: str
    username: str | None = None
    unread_count: int = 0
    pinned: bool = False
    archived: bool = False
    muted: bool = False
    last_message_id: int | None = None
    last_message_at: datetime | None = None
    last_message_preview: str | None = None


class DialogFolder(BaseModel):
    id: int
    title: str
    chat_ids: list[int] = Field(default_factory=list)
    unread_count: int = 0


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
    reactions: list[ReactionSummary] = Field(default_factory=list)
    read: bool = False
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
    phone: str | None = None
    active_route: str | None = None
    source_session_available: bool = False
    client_session_exists: bool = False
    session_dc_id: int | None = None
    session_auth_key_present: bool = False
    session_auth_key_bytes: int = 0
    runtime_session_cloned: bool = False
    last_error: str | None = None


class DeviceSession(BaseModel):
    hash: int
    current: bool = False
    device_model: str
    platform: str
    system_version: str
    app_name: str
    app_version: str
    date_active: datetime
    country: str | None = None
    region: str | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    reply_to_message_id: int | None = Field(default=None, ge=1)


class SendRecentMediaRequest(BaseModel):
    caption: str = Field(default="", max_length=1024)
    reply_to_message_id: int | None = Field(default=None, ge=1)


class EditMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class ForwardMessageRequest(BaseModel):
    target_chat_id: int


class SetReactionRequest(BaseModel):
    emoji: str | None = Field(default=None, max_length=16)


class ProxyLinkRequest(BaseModel):
    link: str


class ProxySelectRequest(BaseModel):
    index: int | None = None


class TypingRequest(BaseModel):
    active: bool = True


class DialogStateRequest(BaseModel):
    enabled: bool


class ApiConfigRequest(BaseModel):
    api_id: int = Field(ge=1)
    api_hash: str = Field(min_length=16, max_length=128)


class LoginPhoneRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=20)


class LoginCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class LoginPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class DesktopError(Exception):
    """Safe application error intended for the local API."""
