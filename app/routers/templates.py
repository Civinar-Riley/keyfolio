"""导出模板 CRUD 与渲染。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, services
from .channels import require_data_key

router = APIRouter(prefix="/api/templates", tags=["templates"])

PLACEHOLDERS = ["{channel_name}", "{key_name}", "{base_url}", "{key}", "{models}", "{models_json}", "{channel_type}"]


class TemplateIn(BaseModel):
    name: str
    client_type: str = ""
    json_template: str


class RenderIn(BaseModel):
    template_id: int
    key_id: int


@router.get("")
def list_templates(_=Depends(require_data_key)):
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM templates ORDER BY builtin DESC, id").fetchall()
    return {
        "templates": [dict(r) for r in rows],
        "placeholders": PLACEHOLDERS,
    }


@router.post("")
def create_template(payload: TemplateIn, _=Depends(require_data_key)):
    if not payload.name.strip():
        raise HTTPException(400, "模板名不能为空")
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO templates(name, client_type, json_template, builtin) VALUES(?,?,?,0)",
            (payload.name.strip(), payload.client_type, payload.json_template),
        )
        template_id = cur.lastrowid
    return {"ok": True, "id": template_id}


@router.put("/{template_id}")
def update_template(template_id: int, payload: TemplateIn, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE templates SET name=?, client_type=?, json_template=? WHERE id=?",
            (payload.name.strip(), payload.client_type, payload.json_template, template_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "模板不存在")
    return {"ok": True}


@router.delete("/{template_id}")
def delete_template(template_id: int, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        row = conn.execute("SELECT builtin FROM templates WHERE id=?", (template_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "模板不存在")
        if row["builtin"]:
            raise HTTPException(400, "内置模板不能删除，可以新建模板替代")
        conn.execute("DELETE FROM templates WHERE id=?", (template_id,))
    return {"ok": True}


@router.post("/render")
def render_template(payload: RenderIn, _=Depends(require_data_key)):
    with db.get_conn() as conn:
        tpl = conn.execute("SELECT * FROM templates WHERE id=?", (payload.template_id,)).fetchone()
        key_row = conn.execute("SELECT * FROM keys WHERE id=?", (payload.key_id,)).fetchone()
    if tpl is None:
        raise HTTPException(404, "模板不存在")
    if key_row is None:
        raise HTTPException(404, "Key 不存在")
    channel = services.get_channel(key_row["channel_id"])
    if channel is None:
        raise HTTPException(404, "渠道不存在")

    with db.get_conn() as conn:
        model_rows = conn.execute(
            "SELECT model_id FROM models WHERE channel_id=? AND enabled=1 ORDER BY model_id",
            (channel["id"],),
        ).fetchall()
    model_ids = [r["model_id"] for r in model_rows]

    rendered = tpl["json_template"]
    for placeholder, value in {
        "{channel_name}": channel["name"],
        "{key_name}": key_row["name"],
        "{base_url}": channel["base_url"],
        "{key}": services.key_plaintext(key_row),
        "{models}": ", ".join(model_ids),
        "{models_json}": json.dumps(model_ids, ensure_ascii=False, indent=2),
        "{channel_type}": channel["type"],
    }.items():
        rendered = rendered.replace(placeholder, value)

    parsed = None
    try:
        parsed = json.loads(rendered)
    except ValueError:
        pass
    return {"ok": True, "rendered": rendered, "parsed": parsed, "is_json": parsed is not None}
