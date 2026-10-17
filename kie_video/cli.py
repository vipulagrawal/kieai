from __future__ import annotations

import argparse
import os
import sys
import urllib.error
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit

from .client import KieAPIError, KieClient

MODEL = "grok-imagine-video-1-5-preview"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kie-video",
        description="Generate and download a video using Kie.ai's Grok Imagine Video 1.5 Preview API.",
    )
    parser.add_argument("--prompt", help="Describe the video or motion you want to generate.")
    parser.add_argument(
        "--image-url",
        action="append",
        help="Publicly accessible image URL to use (repeat for multiple images; up to 7).",
    )
    parser.add_argument(
        "--image-path",
        "--image",
        action="append",
        dest="image_paths",
        type=Path,
        help="Local image file to upload before generation (repeat up to 7 times).",
    )
    parser.add_argument(
        "--aspect-ratio",
        choices=("auto", "1:1", "16:9", "9:16", "3:2", "2:3"),
        default="9:16",
        help="Aspect ratio (default: 9:16); ignored by the API for a single image.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        choices=range(1, 16),
        default=8,
        metavar="SECONDS",
        help="Video duration from 1 to 15 seconds (default: 8).",
    )
    parser.add_argument(
        "--resolution",
        choices=("480p", "720p", "1080p"),
        default="480p",
        help="Video resolution (default: 480p).",
    )
    parser.add_argument(
        "--nsfw-checker",
        action="store_true",
        help="Enable Kie.ai's additional content filtering.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("videos/grok-video.mp4"),
        help="Destination MP4 path (default: videos/grok-video.mp4).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Initial task polling interval in seconds (default: 3).",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=900.0,
        help="Maximum time to wait for generation in seconds (default: 900).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    api_key = os.environ.get("KIE_API_KEY", "").strip()
    if not api_key:
        parser.error("Set the KIE_API_KEY environment variable before running.")
    if args.prompt is not None and not args.prompt.strip():
        parser.error("--prompt must not be empty when provided.")
    if args.prompt is not None and len(args.prompt) > 4096:
        parser.error("--prompt must be 4096 characters or fewer.")
    if args.image_url and args.image_paths:
        parser.error("Use --image-url or --image-path, not both.")
    image_count = len(args.image_url or args.image_paths or [])
    if args.prompt is None and image_count == 0:
        parser.error("Provide --prompt, at least one --image-url, or at least one --image-path.")
    if image_count > 7:
        parser.error("Provide no more than 7 images.")
    if args.image_url:
        for image_url_value in args.image_url:
            image_url = urlsplit(image_url_value)
            if image_url.scheme not in {"http", "https"} or not image_url.netloc:
                parser.error("--image-url values must be absolute HTTP or HTTPS URLs.")
    if args.image_paths:
        for image_path in args.image_paths:
            if not image_path.is_file():
                parser.error(f"Image path is not a file: {image_path}")
            if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                parser.error(f"Unsupported image type: {image_path}")
            if image_path.stat().st_size > 20 * 1024 * 1024:
                parser.error(f"Image exceeds Kie.ai's 20 MB upload limit: {image_path}")
    if args.resolution == "1080p" and image_count > 1:
        parser.error("The 1080p resolution supports only one image.")
    if args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero.")
    if args.poll_timeout <= 0:
        parser.error("--poll-timeout must be greater than zero.")
    if args.output.exists():
        parser.error(f"Refusing to overwrite existing file: {args.output}")

    client = KieClient(api_key)
    input_data = {
        "duration": args.duration,
        "resolution": args.resolution,
        "nsfw_checker": args.nsfw_checker,
    }
    if args.prompt is not None:
        input_data["prompt"] = args.prompt
    if args.image_url:
        input_data["image_urls"] = args.image_url
    if not image_count or image_count > 1:
        input_data["aspect_ratio"] = args.aspect_ratio

    try:
        if args.image_paths:
            input_data["image_urls"] = [
                client.upload_image(image_path) for image_path in args.image_paths
            ]
        task_id = client.create_task(MODEL, input_data)
        print(f"Created Kie.ai task: {task_id}")
        video_url = client.wait_for_completion(
            task_id,
            poll_interval=args.poll_interval,
            poll_timeout=args.poll_timeout,
            on_state=lambda state: print(f"Task state: {state}"),
        )
        output = client.download_video(video_url, args.output)
    except (KieAPIError, OSError, TimeoutError, urllib.error.URLError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Video saved to {output}")
    return 0
