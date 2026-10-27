"""Local-only stand-ins for S3's presigned POST and GET (HLD §6.5), served by the API so
a local run and the e2e tests upload and download without AWS. Mounted only when
debug_env() is true, and kept out of the OpenAPI document.

The checks themselves are LocalObjectStore's: exact key, size range, exact content
type, expiry. Whether S3 applies the same policy is QA's staging check.
"""

from fastapi import APIRouter, Request, Response

from platform_common.errors import Invalid
from platform_common.storage import LocalObjectStore, UploadRefused, get_store

router = APIRouter(include_in_schema=False)


def _local() -> LocalObjectStore:
    store = get_store()
    if not isinstance(store, LocalObjectStore):
        raise RuntimeError("dev object routes need LocalObjectStore")
    return store


@router.post("/dev/objects/upload", status_code=204)
async def upload(request: Request):
    form = await request.form()  # python-multipart, a dev dependency
    file = form.get("file")
    if file is None or isinstance(file, str):
        raise Invalid("upload_refused", "the form has no file", field="file")
    fields = {k: v for k, v in form.items() if isinstance(v, str)}
    try:
        _local().receive_post(fields, await file.read())
    except UploadRefused as e:
        # S3 answers 403 for a policy violation; the e2e tests look for that.
        return Response(status_code=403, content=e.reason)
    return Response(status_code=204)


@router.get("/dev/objects/get/{token}")
def download(token: str):
    try:
        data, content_type, name = _local().open_get(token)
    except UploadRefused:
        return Response(status_code=403)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if name else {}
    return Response(data, media_type=content_type or "application/octet-stream", headers=headers)
