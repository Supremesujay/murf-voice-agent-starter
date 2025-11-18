from pydantic import BaseModel

class UploadFileResponse(BaseModel):
    filename: str
    content_type: str
    file_size: int