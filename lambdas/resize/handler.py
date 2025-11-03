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


def upload_to_s3(bucket: str, key: str, data, content_type: str = "image/jpeg"):
    s3 = boto3.client("s3")
    if isinstance(data, Image.Image):
        buf = io.BytesIO()
        # 强制输出 JPEG（统一）
        data.save(buf, format="JPEG")
        buf.seek(0)
        s3.upload_fileobj(buf, bucket, key, ExtraArgs={"ContentType": content_type})
    elif isinstance(data, (bytes, bytearray)):
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    else:
        # 其他（例如字符串）
        s3.put_object(Bucket=bucket, Key=key, Body=str(data).encode("utf-8"), ContentType=content_type)


# ---------- event parsing ----------
def _iter_s3_records(event):
    """
    同时兼容：
      A) S3 直触发: event["Records"][i]["s3"]
      B) SNS 包裹:  event["Records"][i]["Sns"]["Message"] -> JSON -> Records[].s3
    统一产出 (bucket, key)
    """
    for rec in event.get("Records", []):
        if "Sns" in rec:  # SNS-wrapped S3
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
    print("Resize Lambda triggered")
    ok = 0
    fail = 0

    for bucket_name, object_key in _iter_s3_records(event):
        try:
            print(f"Processing: s3://{bucket_name}/{object_key}")
            img = download_from_s3(bucket_name, object_key)

            # 核心：缩放到 512x512（LANCZOS）
            resized = img.resize((512, 512), Image.Resampling.LANCZOS)

            filename = Path(object_key).name
            out_key = f"processed/resize/{filename}"
            upload_to_s3(bucket_name, out_key, resized, content_type="image/jpeg")
            print(f"Uploaded: s3://{bucket_name}/{out_key}")
            ok += 1
        except Exception as e:
            print(f"❌ Failed: s3://{bucket_name}/{object_key} -> {e}")
            fail += 1

    result = {"statusCode": 200 if fail == 0 else 207, "processed": ok, "failed": fail}
    print(result)
    return result
