from pydantic import BaseModel, Field


class SqlPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class SqlPreviewResponse(BaseModel):
    query: str
    tables: list[str]
    read_only: bool
    max_rows: int
