"""Turn Telethon objects into the API models the desktop UI renders."""

import base64
from typing import Any

from telethon import types, utils

from app.models import LinkPreview, MediaInfo, MessageEntity


_ENTITY_TYPES = {
    "MessageEntityBold": "bold",
    "MessageEntityItalic": "italic",
    "MessageEntityUnderline": "underline",
    "MessageEntityStrike": "strike",
    "MessageEntityCode": "code",
    "MessageEntityPre": "pre",
    "MessageEntitySpoiler": "spoiler",
    "MessageEntityBlockquote": "blockquote",
    "MessageEntityUrl": "url",
    "MessageEntityTextUrl": "text_url",
    "MessageEntityMention": "mention",
    "MessageEntityMentionName": "mention_name",
    "InputMessageEntityMentionName": "mention_name",
    "MessageEntityHashtag": "hashtag",
    "MessageEntityCashtag": "cashtag",
    "MessageEntityBotCommand": "bot_command",
    "MessageEntityEmail": "email",
    "MessageEntityPhone": "phone",
    "MessageEntityCustomEmoji": "custom_emoji",
}


def display_name(entity: Any) -> str | None:
    if entity is None:
        return None
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    name = " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]))
    return name or getattr(entity, "username", None)


def first_name(entity: Any) -> str | None:
    if entity is None:
        return None
    return getattr(entity, "first_name", None) or getattr(entity, "title", None) or display_name(entity)


def entities(message: Any) -> list[MessageEntity]:
    values: list[MessageEntity] = []
    for item in getattr(message, "entities", None) or []:
        kind = _ENTITY_TYPES.get(type(item).__name__)
        if kind is None:
            continue
        user_id = getattr(item, "user_id", None)
        values.append(
            MessageEntity(
                type=kind,
                offset=int(getattr(item, "offset", 0) or 0),
                length=int(getattr(item, "length", 0) or 0),
                url=getattr(item, "url", None),
                user_id=user_id if isinstance(user_id, int) else None,
                language=getattr(item, "language", None) or None,
            )
        )
    return values


def _stripped_thumb(sizes: Any) -> str | None:
    for size in sizes or []:
        if isinstance(size, types.PhotoStrippedSize) and size.bytes:
            try:
                data = utils.stripped_photo_to_jpg(size.bytes)
            except Exception:
                return None
            return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    return None


def _has_real_thumb(sizes: Any) -> bool:
    return any(
        isinstance(size, (types.PhotoSize, types.PhotoSizeProgressive, types.PhotoCachedSize))
        for size in sizes or []
    )


def media_kind(message: Any) -> str | None:
    if not getattr(message, "media", None):
        return None
    if isinstance(message.media, types.MessageMediaWebPage):
        return None
    if getattr(message, "sticker", None):
        return "sticker"
    if getattr(message, "gif", None):
        return "gif"
    if getattr(message, "video_note", None):
        return "video_note"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "document", None):
        return "file"
    return "other"


def _other_media_title(media: Any) -> str:
    if isinstance(media, types.MessageMediaPoll):
        question = getattr(getattr(media, "poll", None), "question", None)
        text = getattr(question, "text", question)
        return "📊 " + str(text or "نظرسنجی")
    if isinstance(media, (types.MessageMediaGeo, types.MessageMediaGeoLive, types.MessageMediaVenue)):
        return "📍 " + str(getattr(media, "title", None) or "موقعیت مکانی")
    if isinstance(media, types.MessageMediaContact):
        name = " ".join(filter(None, [media.first_name, media.last_name]))
        return "👤 " + (name or str(media.phone_number or "مخاطب"))
    if isinstance(media, types.MessageMediaDice):
        return str(media.emoticon or "🎲") + " " + str(media.value)
    return "رسانه"


def media_info(message: Any) -> MediaInfo | None:
    kind = media_kind(message)
    if kind is None:
        return None

    media = message.media
    if kind == "other":
        return MediaInfo(kind="other", title=_other_media_title(media), downloadable=False)

    file_info = getattr(message, "file", None)
    photo = getattr(message, "photo", None)
    document = getattr(message, "document", None)
    sizes = getattr(photo, "sizes", None) if photo is not None else getattr(document, "thumbs", None)
    mime_type = getattr(file_info, "mime_type", None)

    duration = getattr(file_info, "duration", None)
    return MediaInfo(
        kind=kind,
        name=getattr(file_info, "name", None),
        size=getattr(file_info, "size", None),
        mime_type=mime_type,
        playable=kind in {"video", "video_note", "gif", "voice", "audio"},
        downloadable=True,
        width=getattr(file_info, "width", None),
        height=getattr(file_info, "height", None),
        duration=float(duration) if duration is not None else None,
        thumb_data=_stripped_thumb(sizes),
        has_thumb=kind == "photo" or _has_real_thumb(sizes),
        emoji=getattr(file_info, "emoji", None) if kind == "sticker" else None,
        title=getattr(file_info, "title", None),
        performer=getattr(file_info, "performer", None),
        animated=mime_type == "application/x-tgsticker",
    )


def link_preview(message: Any) -> LinkPreview | None:
    media = getattr(message, "media", None)
    if not isinstance(media, types.MessageMediaWebPage):
        return None
    page = media.webpage
    if not isinstance(page, types.WebPage):
        return None
    return LinkPreview(
        url=str(page.url),
        site_name=page.site_name,
        title=page.title,
        description=(page.description or "")[:300] or None,
        has_photo=page.photo is not None,
    )


def forward_name(message: Any) -> str | None:
    header = getattr(message, "fwd_from", None)
    if header is None:
        return None
    forward = getattr(message, "forward", None)
    for candidate in (getattr(forward, "chat", None), getattr(forward, "sender", None)):
        name = display_name(candidate)
        if name:
            return name
    return getattr(header, "from_name", None) or getattr(header, "post_author", None) or "پیام فورواردشده"


def action_text(message: Any, sender_name: str | None) -> str | None:
    if not isinstance(message, types.MessageService):
        return None
    action = message.action
    who = sender_name or "کسی"
    if isinstance(action, (types.MessageActionChatAddUser, types.MessageActionChatJoinedByLink, types.MessageActionChatJoinedByRequest)):
        return f"{who} به گروه پیوست"
    if isinstance(action, types.MessageActionChatDeleteUser):
        return f"{who} گروه را ترک کرد"
    if isinstance(action, types.MessageActionPinMessage):
        return f"{who} یک پیام را سنجاق کرد"
    if isinstance(action, types.MessageActionChatEditTitle):
        return f"{who} نام گروه را به «{action.title}» تغییر داد"
    if isinstance(action, types.MessageActionChatEditPhoto):
        return f"{who} عکس گروه را تغییر داد"
    if isinstance(action, types.MessageActionChatDeletePhoto):
        return f"{who} عکس گروه را حذف کرد"
    if isinstance(action, types.MessageActionChatCreate):
        return f"{who} گروه «{action.title}» را ساخت"
    if isinstance(action, types.MessageActionChannelCreate):
        return f"کانال «{action.title}» ساخته شد"
    if isinstance(action, (types.MessageActionChatMigrateTo, types.MessageActionChannelMigrateFrom)):
        return "گروه به سوپرگروه ارتقا یافت"
    if isinstance(action, types.MessageActionHistoryClear):
        return "تاریخچه پاک شد"
    if isinstance(action, types.MessageActionPhoneCall):
        return "📞 تماس صوتی" if not getattr(action, "video", False) else "📹 تماس تصویری"
    if isinstance(action, types.MessageActionGroupCall):
        return "تماس گروهی"
    if isinstance(action, types.MessageActionContactSignUp):
        return f"{who} به تلگرام پیوست"
    if isinstance(action, types.MessageActionScreenshotTaken):
        return f"{who} از صفحه عکس گرفت"
    return "پیام سرویس"


MEDIA_PREVIEW = {
    "photo": "🖼 عکس",
    "video": "📹 ویدئو",
    "video_note": "پیام ویدئویی",
    "gif": "GIF",
    "voice": "🎤 پیام صوتی",
    "audio": "🎵 موسیقی",
    "file": "📎 فایل",
}


def preview_text(message: Any) -> str | None:
    """One-line dialog list preview, like Telegram's chat list."""
    if message is None:
        return None
    if isinstance(message, types.MessageService):
        return action_text(message, first_name(getattr(message, "sender", None)))
    text = str(getattr(message, "raw_text", None) or "").strip().replace("\n", " ")
    kind = media_kind(message)
    if kind == "sticker":
        emoji = getattr(getattr(message, "file", None), "emoji", None)
        return ((emoji + " ") if emoji else "") + "استیکر"
    if kind == "other":
        label = _other_media_title(message.media)
    elif kind == "file":
        label = "📎 " + str(getattr(getattr(message, "file", None), "name", None) or "فایل")
    elif kind == "audio":
        file_info = getattr(message, "file", None)
        label = "🎵 " + str(getattr(file_info, "title", None) or getattr(file_info, "name", None) or "موسیقی")
    else:
        label = MEDIA_PREVIEW.get(kind or "")
    if label and text:
        return f"{label}، {text}"[:180]
    return (text or label or "")[:180] or None
