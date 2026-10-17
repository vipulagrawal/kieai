from __future__ import annotations

import hmac
import os
import tempfile
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from kie_video.client import KieAPIError, KieClient
from kie_video.cli import MODEL


def _configured_app_password() -> str | None:
    try:
        password = st.secrets["auth"]["password"]
    except (FileNotFoundError, KeyError):
        password = os.environ.get("APP_PASSWORD")
    if not isinstance(password, str) or not password.strip():
        return None
    return password


def _authenticate() -> None:
    candidate = st.session_state.get("app_password_input", "")
    st.session_state["app_password_input"] = ""
    expected = _configured_app_password()
    if expected is not None and hmac.compare_digest(candidate, expected):
        st.session_state["authenticated"] = True
        st.session_state["login_failed"] = False
    else:
        st.session_state["login_failed"] = True


def _capture_submitted_api_key() -> None:
    st.session_state["_submitted_api_key"] = st.session_state.get("kie_api_key_input", "")
    st.session_state["kie_api_key_input"] = ""


st.set_page_config(page_title="Kie.ai Video Generator", page_icon="🎬", layout="centered")

if _configured_app_password() is None:
    st.error(
        "App login is not configured. Set [auth].password in "
        ".streamlit/secrets.toml or set the APP_PASSWORD environment variable."
    )
    st.stop()

if st.session_state.get("authenticated", False) and st.button("Log out"):
    st.session_state["authenticated"] = False
    st.rerun()

if not st.session_state.get("authenticated", False):
    st.title("Kie.ai Video Generator")
    st.caption("Log in to continue.")
    with st.form("app_login"):
        st.text_input("App password", type="password", key="app_password_input")
        st.form_submit_button("Log in", type="primary", on_click=_authenticate)
    if st.session_state.pop("login_failed", False):
        st.error("Incorrect password.")
    st.stop()

st.title("Kie.ai Video Generator")
st.caption("Generate a video with Grok Imagine Video 1.5.")
st.warning(
    "Your API key is used in memory to make Kie.ai requests. This app does not print or "
    "save it. Only enter your key when you trust the server hosting this app; the hosting "
    "provider may still process service traffic."
)
st.info(
    "Uploaded images are sent to Kie.ai, where temporary uploads are deleted after 24 hours. "
    "Video generation may use credits from the API key's account."
)

with st.form("video_generation"):
    st.text_input(
        "Kie.ai API key",
        type="password",
        help="Your key is sent to Kie.ai in the Authorization header.",
        key="kie_api_key_input",
    )
    prompt = st.text_area(
        "Prompt (optional when images are provided)",
        max_chars=4096,
        placeholder="Describe the video or motion you want.",
    )
    image_url = st.text_input(
        "Image URL (optional)",
        placeholder="https://example.com/image.jpg",
        help="Use a public HTTP(S) URL that Kie.ai can access. Do not combine with uploaded images.",
    )
    image_files = st.file_uploader(
        "Images (optional; up to 7, max 20 MB each)",
        type=("jpg", "jpeg", "png", "webp"),
        accept_multiple_files=True,
        max_upload_size=20,
    )
    aspect_ratio = st.selectbox(
        "Aspect ratio",
        ("9:16", "auto", "1:1", "16:9", "3:2", "2:3"),
        help="Ignored by Kie.ai when exactly one image is provided.",
    )
    duration = st.slider("Duration (seconds)", min_value=1, max_value=15, value=8)
    resolution = st.selectbox("Resolution", ("480p", "720p", "1080p"))
    nsfw_checker = st.checkbox("Enable Kie.ai additional content filtering")
    submitted = st.form_submit_button(
        "Generate video",
        type="primary",
        on_click=_capture_submitted_api_key,
    )

if submitted:
    submitted_api_key = st.session_state.pop("_submitted_api_key", "")
    clean_prompt = prompt.strip()
    clean_image_url = image_url.strip()
    if not submitted_api_key.strip():
        st.error("Enter your Kie.ai API key.")
    elif not clean_prompt and not clean_image_url and not image_files:
        st.error("Enter a prompt or upload at least one image.")
    elif clean_image_url and image_files:
        st.error("Provide an image URL or upload image files, not both.")
    elif clean_image_url and (
        urlsplit(clean_image_url).scheme not in {"http", "https"}
        or not urlsplit(clean_image_url).netloc
    ):
        st.error("Image URL must be an absolute HTTP or HTTPS URL.")
    elif len(image_files) > 7:
        st.error("Upload no more than 7 images.")
    elif resolution == "1080p" and len(image_files) > 1:
        st.error("1080p supports only one image.")
    else:
        client = KieClient(submitted_api_key.strip())
        task_input: dict[str, object] = {
            "duration": duration,
            "resolution": resolution,
            "nsfw_checker": nsfw_checker,
        }
        if clean_prompt:
            task_input["prompt"] = clean_prompt
        if (not image_files and not clean_image_url) or len(image_files) > 1:
            task_input["aspect_ratio"] = aspect_ratio

        try:
            with st.status("Preparing your video...", expanded=True) as status:
                if clean_image_url:
                    task_input["image_urls"] = [clean_image_url]
                elif image_files:
                    uploaded_urls = []
                    for image_file in image_files:
                        st.write(f"Uploading {image_file.name}...")
                        uploaded_urls.append(
                            client.upload_image_bytes(image_file.name, image_file.getvalue())
                        )
                    task_input["image_urls"] = uploaded_urls

                task_id = client.create_task(MODEL, task_input)
                st.write("Video task submitted to Kie.ai.")
                result_url = client.wait_for_completion(
                    task_id,
                    on_state=lambda state: status.write(f"Task state: {state}"),
                )
                with tempfile.TemporaryDirectory() as temporary_directory:
                    video_path = Path(temporary_directory) / "generated-video.mp4"
                    client.download_video(result_url, video_path)
                    video_bytes = video_path.read_bytes()
                status.update(label="Video ready", state="complete", expanded=False)

            st.video(video_bytes)
            st.download_button(
                "Download video",
                data=video_bytes,
                file_name="grok-video.mp4",
                mime="video/mp4",
                type="primary",
            )
        except (KieAPIError, OSError, TimeoutError, urllib.error.URLError, ValueError) as error:
            st.error(f"Could not generate the video: {error}")
