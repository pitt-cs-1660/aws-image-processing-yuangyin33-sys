import json
import io
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from PIL import Image


# ---------- S3 helpers ----------
def download_from_s3(bucket: str, key: str) -> Image.Image:
    s3 = boto3.client("s3")
    buf = io.BytesIO()
    s3.download_fileobj(bucket, key, buf)
    buf.seek(0)
    return Image.open(buf)


def upload_to_s3(bucket: str, key: str, data, content_type: str = "application/json"):
    s3 = boto3.client("s3")
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    elif isinstance(data, (bytes, bytearray)):
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    else:
        s3.put_object(Bucket=bucket, Key=key, Body=str(data).encode("utf-8"), ContentType=content_type)


# ---------- event parsing ----------
def _iter_s3_records(event):
    for rec in event.get("Records", []):
        if "Sns" in rec:  # SNS-wrapped
            try:
                msg = rec["Sns"]["Message"]
                payload = json.loads(msg)
                for s3ev in payload.get("Records", []):
                    s3r = s3ev.get("s3", {})
                    bucket = s3r.get("bucket", {}).get("name")
                    key = s3r.get("object", {}).get("key")
                    if bucket and key:
                        yield bucket, unquote_plus(key)
            except Exception:
                continue
        else:  # native S3
            s3r = rec.get("s3", {})
            bucket = s3r.get("bucket", {}).get("name")
            key = s3r.get("object", {}).get("key")
            if bucket and key:
                yield bucket, unquote_plus(key)


# ---------- lambda entry ----------
def handler(event, context):
    print("EXIF Lambda triggered")
    ok = 0
    fail = 0

    for bucket_name, object_key in _iter_s3_records(event):
        try:
            print(f"Processing: s3://{bucket_name}/{object_key}")
            img = download_from_s3(bucket_name, object_key)

            # 基础元信息
            exif_data = {
                "width": img.width,
                "height": img.height,
                "format": getattr(img, "format", None),
                "mode": img.mode,
                "source_key": object_key,
            }

            # EXIF 标签（如果有）
            try:
                if hasattr(img, "getexif"):
                    exif = img.getexif()
                    if exif:
                        for tag_id, value in exif.items():
                            # Pillow 的 EXIF tag_id 是整型，这里转成字符串，避免 JSON 不兼容
                            exif_data[str(tag_id)] = str(value)
            except Exception as tag_e:
                exif_data["exif_parse_error"] = str(tag_e)

            # 输出 JSON（与作业约定路径）
            filename = Path(object_key).stem  # 去掉扩展名
            out_key = f"processed/exif/{filename}.json"
            upload_to_s3(bucket_name, out_key, exif_data, content_type="application/json")
            print(f"Uploaded: s3://{bucket_name}/{out_key}")
            ok += 1
        except Exception as e:
            print(f"❌ Failed: s3://{bucket_name}/{object_key} -> {e}")
            fail += 1

    result = {"statusCode": 200 if fail == 0 else 207, "processed": ok, "failed": fail}
    print(result)
    return result
