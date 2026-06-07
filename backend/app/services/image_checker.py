import magic
import imagehash
from PIL import Image
import io

MAX_FILE_SIZE_MB = 5
MAX_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"]

def validate_and_extract_image_data(file_bytes: bytes) -> dict:
    if len(file_bytes) > MAX_BYTES:
        return {"is_valid": False, "error": f"File exceeds {MAX_FILE_SIZE_MB}MB limit."}

    mime_type = magic.from_buffer(file_bytes, mime=True)
    if mime_type not in ALLOWED_MIME_TYPES:
        return {"is_valid": False, "error": "Invalid file type. Only JPEG/PNG/WEBP allowed."}

    try:
        image = Image.open(io.BytesIO(file_bytes))
        phash = str(imagehash.phash(image))
        
        metadata = {
            "format": image.format,
            "mode": image.mode,
            "size": image.size,
        }
        
        exif_data = image.getexif()
        metadata["has_exif"] = bool(exif_data)

        return {
            "is_valid": True,
            "image_hash": phash,
            "metadata": metadata
        }
        
    except Exception as e:
        return {"is_valid": False, "error": f"Image processing failed: {str(e)}"}