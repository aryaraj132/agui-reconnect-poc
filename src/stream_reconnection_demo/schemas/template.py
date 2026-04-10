from pydantic import BaseModel


class TemplateSection(BaseModel):
    id: str
    type: str  # header, body, footer, cta, image
    content: str
    styles: dict[str, str] = {}


class EmailTemplate(BaseModel):
    html: str = ""
    css: str = ""
    subject: str = ""
    preview_text: str = ""
    sections: list[TemplateSection] = []
    version: int = 1
