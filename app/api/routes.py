import asyncio

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.models import (
    DesktopError,
    EditMessageRequest,
    ForwardMessageRequest,
    LoginCodeRequest,
    LoginPasswordRequest,
    LoginPhoneRequest,
    SendMessageRequest,
)
from app.telegram.uploads import cleanup_staged_upload, stage_upload

router = APIRouter()


def service(request: Request):
    return request.app.state.telegram_desktop


def error_response(error: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(error))


@router.get("/api/telegram/status")
async def status(request: Request):
    return service(request).status


@router.get("/api/telegram/transport")
async def transport(request: Request):
    return {
        "routes": service(request).transport.snapshot(),
        "allow_direct": service(request).settings.telegram_allow_direct,
    }


@router.post("/api/telegram/session/import")
async def import_session(request: Request):
    try:
        return await service(request).import_source()
    except DesktopError as exc:
        raise error_response(exc) from None


@router.get("/api/telegram/dialogs")
async def dialogs(request: Request, search: str | None = None):
    try:
        return await service(request).list_dialogs(search)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.get("/api/telegram/chats/{chat_id}")
async def chat_info(chat_id: int, request: Request):
    try:
        return await service(request).chat_info(chat_id)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.get("/api/telegram/chats/{chat_id}/photo")
async def chat_photo(chat_id: int, request: Request):
    try:
        item = await service(request).download_chat_photo(chat_id)
    except DesktopError as exc:
        raise error_response(exc) from None
    return FileResponse(
        path=item.path,
        media_type=item.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/api/telegram/chats/{chat_id}/messages")
async def messages(
    chat_id: int,
    request: Request,
    limit: int = 50,
    offset_id: int = 0,
):
    try:
        return await service(request).history(chat_id, limit, offset_id)
    except (DesktopError, ValueError) as exc:
        raise error_response(exc) from None


@router.get("/api/telegram/chats/{chat_id}/search")
async def search_messages(
    chat_id: int,
    request: Request,
    q: str,
    limit: int = 50,
):
    try:
        return await service(request).search_messages(chat_id, q, limit)
    except (DesktopError, ValueError) as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/chats/{chat_id}/read")
async def mark_read(chat_id: int, request: Request):
    try:
        return await service(request).mark_read(chat_id)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.get("/api/telegram/chats/{chat_id}/messages/{message_id}/media")
async def media(
    chat_id: int,
    message_id: int,
    request: Request,
    download: bool = False,
):
    try:
        item = await service(request).download_media(chat_id, message_id)
    except DesktopError as exc:
        raise error_response(exc) from None

    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=item.path,
        media_type=item.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{item.filename}"'},
    )


@router.post("/api/telegram/chats/{chat_id}/messages")
async def send_message(chat_id: int, values: SendMessageRequest, request: Request):
    try:
        return await service(request).send_text(
            chat_id,
            values.text,
            values.reply_to_message_id,
        )
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/chats/{chat_id}/files")
async def send_file(
    chat_id: int,
    request: Request,
    file: UploadFile = File(...),
    caption: str = Form(""),
    reply_to_message_id: int | None = Form(None),
):
    desktop = service(request)
    if not desktop.status.connected or not desktop.status.authorized:
        raise error_response(DesktopError("Telegram is not connected and authorized"))

    staged = None
    try:
        root = desktop.settings.project_root / "data" / "telegram_desktop" / "uploads"
        staged = await asyncio.to_thread(
            stage_upload,
            file.file,
            root,
            file.filename,
        )
        return await desktop.send_file(
            chat_id,
            str(staged.path),
            caption.strip(),
            reply_to_message_id,
        )
    except (DesktopError, ValueError) as exc:
        raise error_response(exc) from None
    finally:
        await file.close()
        if staged is not None:
            await asyncio.to_thread(cleanup_staged_upload, staged.path)


@router.post("/api/telegram/chats/{chat_id}/messages/{message_id}/edit")
async def edit_message(
    chat_id: int,
    message_id: int,
    values: EditMessageRequest,
    request: Request,
):
    try:
        return await service(request).edit_text(chat_id, message_id, values.text)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/chats/{chat_id}/messages/{message_id}/delete")
async def delete_message(chat_id: int, message_id: int, request: Request):
    try:
        return await service(request).delete_message(chat_id, message_id)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/chats/{chat_id}/messages/{message_id}/forward")
async def forward_message(
    chat_id: int,
    message_id: int,
    values: ForwardMessageRequest,
    request: Request,
):
    try:
        return await service(request).forward_message(
            chat_id,
            message_id,
            values.target_chat_id,
        )
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/auth/send-code")
async def send_code(values: LoginPhoneRequest, request: Request):
    try:
        return await service(request).send_login_code(values.phone)
    except (DesktopError, ValueError) as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/auth/verify-code")
async def verify_code(values: LoginCodeRequest, request: Request):
    try:
        return await service(request).verify_code(values.code)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/auth/verify-password")
async def verify_password(values: LoginPasswordRequest, request: Request):
    try:
        return await service(request).verify_password(values.password)
    except DesktopError as exc:
        raise error_response(exc) from None


@router.post("/api/telegram/auth/logout")
async def logout(request: Request):
    await service(request).logout()
    return service(request).status


@router.websocket("/ws/telegram")
async def websocket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    allowed = {
        None,
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    }
    if origin not in allowed:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    desktop = websocket.app.state.telegram_desktop
    queue = desktop.events.subscribe()
    try:
        await websocket.send_json({"type": "READY", "data": desktop.status.model_dump(mode="json")})
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        desktop.events.unsubscribe(queue)
