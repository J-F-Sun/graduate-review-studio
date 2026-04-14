from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from graduate_review.exporter import ExportError, build_markdown_export, write_docx_export, write_pdf_export
from graduate_review.jobs import JobManager
from graduate_review.rules import DEFAULT_RULES, extract_text_from_rule_file, parse_rule_content
from graduate_review.storage import Storage
from graduate_review.utils import clean_text


class AccessLogNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if " 304 " not in message:
            return True
        return not ('"GET /files/' in message or '"GET /static/' in message)


APP_ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")
access_logger = logging.getLogger("uvicorn.access")
access_logger.addFilter(AccessLogNoiseFilter())
storage = Storage(APP_ROOT)
jobs = JobManager(storage, APP_ROOT)

app = FastAPI(title="Graduate Thesis Review")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
app.mount("/files", StaticFiles(directory=storage.data_dir), name="files")


@app.on_event("startup")
async def recover_interrupted_jobs() -> None:
    recovered = storage.recover_interrupted_jobs()
    logger.info("startup recovery completed recovered_jobs=%s", len(recovered))


def _paper_payload(paper_id: str) -> dict[str, Any]:
    metadata = storage.read_paper_metadata(paper_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Paper not found.")
    parsed = storage.read_parsed(paper_id)
    review = storage.read_review(paper_id)
    return {
        "metadata": metadata,
        "parsed": parsed,
        "review": review,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(APP_ROOT / "static" / "index.html")


@app.get("/api/overview")
async def overview() -> JSONResponse:
    settings = storage.read_settings()
    masked_settings = settings | {
        "llm": settings["llm"] | {
            "api_key": "已配置" if settings["llm"].get("api_key") else "",
        }
    }
    return JSONResponse(
        {
            "papers": storage.list_papers(),
            "rules": storage.list_rules(),
            "builtin_rules": DEFAULT_RULES,
            "settings": masked_settings,
        }
    )


@app.post("/api/papers")
async def upload_paper(
    title: str = Form(""),
    degree_type: str = Form(...),
    review_mode: str = Form(...),
    file: UploadFile = File(...),
) -> JSONResponse:
    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".docx", ".pdf"}:
        raise HTTPException(status_code=400, detail="仅支持 docx 与 pdf 论文文件。")
    metadata = storage.create_paper(
        title=title,
        degree_type=degree_type,
        review_mode=review_mode,
        original_filename=filename,
        file_bytes=await file.read(),
    )
    logger.info("paper uploaded paper_id=%s title=%s source=%s", metadata["id"], title, filename)
    jobs.enqueue_parse(metadata["id"])
    return JSONResponse(metadata)


@app.get("/api/papers")
async def list_papers() -> JSONResponse:
    return JSONResponse(storage.list_papers())


@app.get("/api/papers/{paper_id}")
async def get_paper(paper_id: str) -> JSONResponse:
    return JSONResponse(_paper_payload(paper_id))


@app.post("/api/papers/{paper_id}/parse")
async def reparse_paper(paper_id: str) -> JSONResponse:
    if not storage.read_paper_metadata(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found.")
    logger.info("paper reparse requested paper_id=%s", paper_id)
    jobs.enqueue_parse(paper_id)
    return JSONResponse({"ok": True})


@app.post("/api/papers/{paper_id}/review")
async def review_paper(paper_id: str, payload: dict[str, Any]) -> JSONResponse:
    if not storage.read_paper_metadata(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found.")
    logger.info(
        "paper review requested paper_id=%s mode=%s rule_count=%s builtin_rule_count=%s",
        paper_id,
        payload.get("review_mode"),
        len(payload.get("rule_ids", [])),
        len(payload.get("builtin_rule_ids", [])),
    )
    jobs.enqueue_review(
        paper_id,
        review_mode=payload.get("review_mode"),
        rule_ids=payload.get("rule_ids", []),
        builtin_rule_ids=payload.get("builtin_rule_ids"),
    )
    return JSONResponse({"ok": True})


@app.patch("/api/papers/{paper_id}")
async def update_paper(paper_id: str, payload: dict[str, Any]) -> JSONResponse:
    metadata = storage.read_paper_metadata(paper_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Paper not found.")
    updates: dict[str, Any] = {}
    if "title" in payload:
        title = clean_text(str(payload.get("title", "")))
        if not title:
            raise HTTPException(status_code=400, detail="论文标题不能为空。")
        updates["title"] = title
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的字段。")
    updated = storage.update_paper_metadata(paper_id, **updates)
    return JSONResponse(updated)


@app.delete("/api/papers/{paper_id}")
async def delete_paper(paper_id: str) -> JSONResponse:
    if not storage.read_paper_metadata(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found.")
    logger.info("paper delete requested paper_id=%s", paper_id)
    jobs.cancel_tasks_for_paper(paper_id)
    storage.delete_paper(paper_id)
    return JSONResponse({"ok": True})


@app.delete("/api/home")
async def reset_home() -> JSONResponse:
    logger.info("home reset requested")
    jobs.cancel_all_tasks()
    storage.clear_all_papers()
    return JSONResponse({"ok": True})


@app.get("/api/papers/{paper_id}/export")
async def export_review(
    paper_id: str,
    format: str = Query("markdown"),
) -> FileResponse:
    payload = _paper_payload(paper_id)
    settings = storage.read_settings()
    source_path = storage.get_source_path(paper_id)

    try:
        if format == "markdown":
            export_path = storage.exports_dir / f"{paper_id}.md"
            markdown = build_markdown_export(
                payload["metadata"],
                payload["parsed"],
                payload["review"],
                settings,
            )
            export_path.write_text(markdown, encoding="utf-8")
            return FileResponse(export_path, media_type="text/markdown", filename=f"{paper_id}.md")

        if format == "pdf":
            export_path = storage.exports_dir / f"{paper_id}.pdf"
            write_pdf_export(
                payload["metadata"],
                payload["parsed"],
                payload["review"],
                settings,
                export_path,
            )
            return FileResponse(export_path, media_type="application/pdf", filename=f"{paper_id}.pdf")

        if format == "docx":
            export_path = storage.exports_dir / f"{paper_id}.docx"
            write_docx_export(
                payload["metadata"],
                payload["parsed"],
                payload["review"],
                settings,
                source_path=source_path,
                data_root=storage.data_dir,
                output_path=export_path,
            )
            return FileResponse(
                export_path,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=f"{paper_id}.docx",
            )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail="仅支持 markdown、pdf、docx 三种导出格式。")


@app.post("/api/rules")
async def create_rule(
    name: str = Form(...),
    content: str = Form(""),
    file: UploadFile | None = File(default=None),
) -> JSONResponse:
    extracted_content = clean_text(content)
    source_format = "text"
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".txt", ".md", ".docx", ".pdf"}:
            raise HTTPException(status_code=400, detail="仅支持 txt、md、docx、pdf 规则文件。")
        temp_path = storage.data_dir / "_rule_upload" / file.filename
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(await file.read())
        extracted_content = extract_text_from_rule_file(temp_path)
        temp_path.unlink(missing_ok=True)
        source_format = suffix.lstrip(".")
    if not extracted_content:
        raise HTTPException(status_code=400, detail="规则内容不能为空。")
    rule = storage.create_rule(name=name, source_format=source_format, content=extracted_content)
    parsed_items = parse_rule_content(extracted_content)
    rule = storage.update_rule(rule["id"], items=parsed_items)
    return JSONResponse(rule)


@app.patch("/api/rules/{rule_id}")
async def update_rule(rule_id: str, payload: dict[str, Any]) -> JSONResponse:
    if not storage.read_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found.")
    updated = storage.update_rule(rule_id, **payload)
    return JSONResponse(updated)


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: str) -> JSONResponse:
    if not storage.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found.")
    return JSONResponse({"ok": True})


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    settings = storage.read_settings()
    return JSONResponse(
        settings | {"llm": settings["llm"] | {"api_key": "已配置" if settings["llm"].get("api_key") else ""}}
    )


@app.put("/api/settings")
async def update_settings(payload: dict[str, Any]) -> JSONResponse:
    current = storage.read_settings()
    llm_updates = payload.get("llm", {})
    if llm_updates.get("api_key") == "":
        llm_updates["api_key"] = current["llm"].get("api_key", "")
    settings = storage.write_settings({"llm": llm_updates, "export": payload.get("export", {})})
    return JSONResponse(settings | {"llm": settings["llm"] | {"api_key": "已配置" if settings["llm"].get("api_key") else ""}})
