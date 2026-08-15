"""
GBO — Cloudflare R2 storage client (video uploads).

Used for VIDEO specifically, in place of Supabase Storage -- Supabase
Storage's free tier caps out at 1GB total, and video eats through that
fast (Ryker hit this after building pitch clip upload/matching for
Game Tracking). Cloudflare R2's free tier is 10GB/month with no
egress/download fees, at zero cost as long as usage stays under that.
Player/staff PHOTOS stay on Supabase Storage (player-photos/
staff-photos buckets) -- they're tiny and were never the problem, so
only video moved.

One R2 bucket total (not one per video category like Supabase had) --
each category gets its own folder prefix inside it instead
(bucket_subfolder param), so Ryker only has to set up ONE bucket.

Reads R2_* credentials the same way supabase_client.py reads
SUPABASE_* ones: from a local .env file (via python-dotenv) when
running on a laptop, or from the deployment platform's own environment
variables in production.

One-time setup (in the Cloudflare dashboard, all free):
  1. R2 object storage -> Create bucket (e.g. "gbo-videos").
  2. Open the bucket -> Settings -> Public Development URL -> Enable
     (type "allow" to confirm). Copy the public r2.dev URL shown there
     -> R2_PUBLIC_URL_BASE. Note: Cloudflare calls this URL
     "development"/rate-limited, but for a single team's game film
     traffic that's not a real concern -- a custom domain is the
     "production" alternative if it ever becomes one, at the cost of
     needing your own domain added to Cloudflare.
  3. R2 -> Manage API Tokens -> Create API Token -> scope it to just
     this bucket, with Object Read & Write permissions. Copy the
     Access Key ID -> R2_ACCESS_KEY_ID, Secret Access Key ->
     R2_SECRET_ACCESS_KEY. Copy your Account ID (shown on the R2
     Overview page, top right) -> R2_ACCOUNT_ID.
  4. Add R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
     R2_BUCKET_NAME, R2_PUBLIC_URL_BASE to .env (see .env.example) or
     Streamlit Cloud's secrets manager.

Existing clips already uploaded to Supabase Storage keep working --
their video_url values still point at Supabase and aren't migrated by
this change. Only NEW uploads go to R2 going forward.
"""

import os
import uuid
from dotenv import load_dotenv
import boto3
from botocore.config import Config

load_dotenv()


def _get_secret(key: str):
    return os.environ.get(key)


R2_ACCOUNT_ID = _get_secret("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = _get_secret("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _get_secret("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = _get_secret("R2_BUCKET_NAME")
R2_PUBLIC_URL_BASE = _get_secret("R2_PUBLIC_URL_BASE")  # e.g. https://pub-xxxxxxxx.r2.dev -- no trailing slash


def get_r2_client():
    """boto3 S3-compatible client pointed at R2's S3 API endpoint.
    R2 is fully S3-API-compatible, so the regular boto3 "s3" client
    works unmodified -- only the endpoint_url differs from real AWS."""
    if not (R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        raise RuntimeError(
            "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY must be set in .env "
            "(see .env.example) -- create these in the Cloudflare dashboard under "
            "R2 -> Manage API Tokens -> Create API Token."
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_video_to_r2(uploaded_file, identifier: str, bucket_subfolder: str = ""):
    """Upload one file to R2 and return its public URL. bucket_subfolder
    (e.g. "pitch-videos/", "routine-videos/") keeps the different video
    categories from colliding in the single shared R2 bucket, the same
    way separate Supabase buckets used to keep them apart. Raises on
    failure -- callers catch it and show an error with setup guidance,
    same pattern as the old Supabase upload helpers.

    uploaded_file needs a .name, a .getvalue() -> bytes, and optionally
    a .type -- Streamlit's UploadedFile satisfies this directly. Shiny's
    ui.input_file() instead returns a dict with "name"/"datapath" (a
    path on disk, no in-memory bytes) -- the Shiny UI layer will need a
    small adapter object (or a call-site tweak reading the file from
    datapath) when video upload pages are migrated; not a change to
    this function's contract, just a note for that migration step."""
    if not (R2_BUCKET_NAME and R2_PUBLIC_URL_BASE):
        raise RuntimeError(
            "R2_BUCKET_NAME and R2_PUBLIC_URL_BASE must be set in .env (see .env.example)."
        )
    client = get_r2_client()
    ext = uploaded_file.name.split(".")[-1].lower()
    path = f"{bucket_subfolder}{identifier}_{uuid.uuid4().hex[:8]}.{ext}"
    file_bytes = uploaded_file.getvalue()
    content_type = getattr(uploaded_file, "type", None) or "application/octet-stream"
    client.put_object(Bucket=R2_BUCKET_NAME, Key=path, Body=file_bytes, ContentType=content_type)
    return f"{R2_PUBLIC_URL_BASE.rstrip('/')}/{path}"
