from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
import boto3
import os
import re
from datetime import datetime, timezone
from botocore.exceptions import ClientError

app = FastAPI(
    title="Final Sistemas Operativos - FastAPI + S3",
    description="API para subir y consultar imágenes almacenadas en Amazon S3",
    version="1.0.0"
)

BUCKET_NAME = os.getenv("S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")

if not BUCKET_NAME:
    raise RuntimeError("La variable de entorno S3_BUCKET no está configurada")

s3_client = boto3.client("s3", region_name=AWS_REGION)

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def normalize_username(username: str) -> str:
    username = username.strip()

    if not username:
        raise HTTPException(status_code=400, detail="El nombre de usuario no puede estar vacío")

    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise HTTPException(
            status_code=400,
            detail="El usuario solo puede contener letras, números, guion y guion bajo"
        )

    return username


def validate_image(file: UploadFile):
    filename = file.filename or ""
    extension = os.path.splitext(filename.lower())[1]

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Formato inválido. Solo se permiten imágenes PNG, JPG o JPEG"
        )

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Tipo de contenido inválido. Solo se permiten image/png o image/jpeg"
        )


@app.get("/")
def root():
    return {
        "message": "API FastAPI + S3 funcionando correctamente",
        "docs": "/docs"
    }


@app.post("/imagenes")
async def upload_image(
    username: str = Form(...),
    image: UploadFile = File(...)
):
    user = normalize_username(username)
    validate_image(image)

    content = await image.read()

    if not content:
        raise HTTPException(status_code=400, detail="La imagen está vacía")

    filename = os.path.basename(image.filename)
    key = f"usuarios/{user}/{filename}"

    stored_at = datetime.now(timezone.utc).isoformat()

    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=image.content_type,
            Metadata={
                "username": user,
                "stored_at": stored_at
            }
        )

        return {
            "message": "Imagen almacenada correctamente en S3",
            "usuario": user,
            "imagen": filename,
            "s3_key": key,
            "fecha_almacenamiento": stored_at
        }

    except ClientError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir la imagen a S3: {str(e)}"
        )


@app.get("/imagenes")
def get_image(
    username: str = Query(...),
    image_name: str = Query(...)
):
    user = normalize_username(username)
    filename = os.path.basename(image_name)

    user_prefix = f"usuarios/{user}/"
    key = f"{user_prefix}{filename}"

    try:
        user_objects = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=user_prefix,
            MaxKeys=1
        )

        if "Contents" not in user_objects:
            raise HTTPException(
                status_code=404,
                detail=f"El usuario '{user}' no existe en el bucket S3"
            )

        object_metadata = s3_client.head_object(
            Bucket=BUCKET_NAME,
            Key=key
        )

        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": key
            },
            ExpiresIn=3600
        )

        metadata = object_metadata.get("Metadata", {})
        fecha_almacenamiento = metadata.get("stored_at")

        return {
            "message": "Imagen encontrada correctamente",
            "usuario": user,
            "imagen": filename,
            "url": presigned_url,
            "fecha_almacenamiento_metadata": fecha_almacenamiento,
            "fecha_ultima_modificacion_s3": object_metadata["LastModified"].isoformat(),
            "url_expira_en_segundos": 3600
        }

    except HTTPException:
        raise

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code in ["404", "NoSuchKey", "NotFound"]:
            raise HTTPException(
                status_code=404,
                detail=f"La imagen '{filename}' no existe para el usuario '{user}'"
            )

        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar S3: {str(e)}"
        )
