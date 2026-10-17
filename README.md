# Kie.ai Video Generator

A small Python command-line starter that creates video tasks with Kie.ai's Grok Imagine Video 1.5 Preview API, polls until they finish, and downloads the generated MP4.

## Requirements

- Python 3.10 or newer
- A Kie.ai API key from [kie.ai/api-key](https://kie.ai/api-key)

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:KIE_API_KEY = "your-api-key"
```

Keep the API key in the environment; do not put it in source code or commit it.

## Web interface

The browser interface requires a shared app password. For local use, create
`.streamlit/secrets.toml` with a strong password:

```toml
[auth]
password = "replace-with-a-long-unique-password"
```

Alternatively, set the `APP_PASSWORD` environment variable. Keep the password
out of source control. For Streamlit Community Cloud, add the same `[auth]`
section in the app's **Settings > Secrets**.

Install the project, then run the browser interface locally:

```powershell
python -m pip install -e .
python -m streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit and sign in with the shared app password.
Then enter your own Kie.ai API key in the password field and provide a prompt
and/or upload images or a public image URL. On submit, the app clears the API key
widget and uses the submitted key in memory to authorize Kie.ai requests. The app
does not print, log, or write the key to a file. The shared password provides
basic access control, not individual user accounts. Do not use the interface on
a server you do not trust: hosting providers may process service traffic, so the
app cannot guarantee that a provider never observes request data.

In the web form, use **Image URL (optional)** to provide a public HTTP(S) image URL directly instead of uploading a file. Use either that field or image uploads, not both; Kie.ai must be able to fetch the URL.

To deploy with Streamlit Community Cloud, push this repository to GitHub, create an app from the repository, and select `streamlit_app.py` as the app file. Users can supply their own API keys in the interface; do not add a shared Kie.ai key to the deployment's secrets.

## Generate a video

```powershell
kie-video --prompt "A cinematic drone shot over a misty mountain lake at sunrise"
```

The video is saved to `videos/grok-video.mp4` by default. Existing files are never overwritten. Set another path with `--output`.

To animate an image, pass its publicly accessible HTTP(S) URL with `--image-url`. Optionally describe the motion with `--prompt`:

```powershell
kie-video `
  --image-url "https://example.com/my-image.jpg" `
  --prompt "The camera slowly pushes in as the leaves move in the breeze" `
  --duration 8 `
  --output videos/animated-image.mp4
```

You can instead pass a local file path with `--image-path` (or `--image`). The CLI uploads the image to Kie.ai, takes the returned `downloadUrl`, and passes it to Grok Imagine Video 1.5:

```powershell
kie-video `
  --image-path "D:\Images\my-image.jpg" `
  --prompt "The camera slowly pushes in as the leaves move in the breeze" `
  --output videos/animated-image.mp4
```

Repeat `--image-path` for multiple local images (up to 7). Local uploads support JPEG, PNG, and WEBP up to 20 MB each. Kie.ai's temporary uploaded file URLs expire after 24 hours. Uploads use Kie.ai's [File Stream Upload API](https://docs.kie.ai/file-upload-api/upload-file-stream); Kie.ai says file uploads are free.

A sample JPEG for trying the local upload flow is available at `tests/fixtures/sample.jpg`. The upload API request is covered by a mocked unit test; run the test suite with `python -m unittest discover -s tests -v`. The test verifies the multipart request and returned URL without making a live API request or requiring an API key.

The `--image-url` option can be repeated up to 7 times; Kie.ai must be able to access each URL. Images may be JPEG, PNG, or WEBP and up to 20 MB each. At 1080p, only one image is supported. For example:

```powershell
kie-video `
  --image-url "https://example.com/first.jpg" `
  --image-url "https://example.com/second.png" `
  --prompt "A smooth transition between these scenes" `
  --aspect-ratio 16:9 `
  --resolution 720p
```

```powershell
kie-video `
  --prompt "A paper airplane gliding through a sunlit room" `
  --duration 8 `
  --resolution 720p `
  --output videos/paper-airplane.mp4
```

Supported options:

- Aspect ratio: `auto`, `1:1`, `16:9`, `9:16`, `3:2`, or `2:3` (default `9:16`)
- Duration: 1–15 seconds (default 8)
- Resolution: `480p`, `720p`, or `1080p`
- Additional content filtering: enabled with `--nsfw-checker` (off by default)
- Polling can be tuned with `--poll-interval` and `--poll-timeout`

The prompt is optional when image URLs are provided and supports up to 4096 characters. Aspect ratio is ignored for a single image. Resolution defaults to `480p`. The Video 1.5 Preview API does not support the earlier Grok model's `mode` option. The command submits `grok-imagine-video-1-5-preview` to Kie.ai's unified `POST /api/v1/jobs/createTask` endpoint and checks `GET /api/v1/jobs/recordInfo`. Generation may consume account credits; check [current pricing](https://kie.ai/pricing) before submitting requests. Kie.ai's generated media is retained for a limited time, so download results you want to keep.

## Run tests

```powershell
python -m unittest discover -s tests -v
```
