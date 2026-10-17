import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kie_video.client import KieAPIError, KieClient
from kie_video.cli import main


class KieClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = KieClient("test-key")

    def test_create_task_returns_task_id(self) -> None:
        with patch.object(
            self.client,
            "_request_json",
            return_value={"code": 200, "data": {"taskId": "task-123"}},
        ) as request_json:
            task_id = self.client.create_task(
                "grok-imagine/text-to-video",
                {"prompt": "A sunrise over the sea"},
            )

        self.assertEqual(task_id, "task-123")
        request_json.assert_called_once_with(
            "/api/v1/jobs/createTask",
            method="POST",
            body={
                "model": "grok-imagine/text-to-video",
                "input": {"prompt": "A sunrise over the sea"},
            },
        )

    def test_wait_for_completion_polls_and_returns_video_url(self) -> None:
        responses = [
            {"code": 200, "data": {"state": "generating"}},
            {
                "code": 200,
                "data": {"state": "success", "response": {"resultUrls": ["https://cdn.test/video.mp4"]}},
            },
        ]
        states: list[str] = []
        with (
            patch.object(self.client, "_request_json", side_effect=responses),
            patch("kie_video.client.time.sleep"),
        ):
            result_url = self.client.wait_for_completion(
                "task-123",
                on_state=states.append,
            )

        self.assertEqual(result_url, "https://cdn.test/video.mp4")
        self.assertEqual(states, ["generating", "success"])

    def test_wait_for_completion_parses_result_json(self) -> None:
        response = {
            "code": 200,
            "data": {
                "state": "success",
                "resultJson": json.dumps({"resultUrls": ["https://cdn.test/video.mp4"]}),
            },
        }
        with patch.object(self.client, "_request_json", return_value=response):
            result_url = self.client.wait_for_completion("task-123")

        self.assertEqual(result_url, "https://cdn.test/video.mp4")

    def test_failed_task_raises_api_error(self) -> None:
        response = {
            "code": 200,
            "data": {"state": "fail", "failCode": "500", "failMsg": "Generation failed"},
        }
        with patch.object(self.client, "_request_json", return_value=response):
            with self.assertRaisesRegex(KieAPIError, "Generation failed"):
                self.client.wait_for_completion("task-123")

    def test_api_error_code_is_checked_even_on_successful_response(self) -> None:
        response = {"code": 401, "msg": "Invalid API key"}
        with patch("kie_video.client.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            with self.assertRaisesRegex(KieAPIError, "Invalid API key"):
                self.client._request_json("/api/v1/jobs/createTask", method="POST", body={})

    def test_download_refuses_to_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "video.mp4"
            destination.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                self.client.download_video("https://cdn.test/video.mp4", destination)
            self.assertEqual(destination.read_bytes(), b"existing")

    def test_download_saves_video_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "video.mp4"
            with patch(
                "kie_video.client.urllib.request.urlopen",
                return_value=io.BytesIO(b"video-data"),
            ):
                result = self.client.download_video("https://cdn.test/video.mp4", destination)

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b"video-data")

    def test_upload_image_returns_download_url_and_sends_multipart(self) -> None:
        upload_response = {
            "code": 200,
            "data": {"downloadUrl": "https://tempfile.test/sample.jpg"},
        }
        image_path = Path(__file__).parent / "fixtures" / "sample.jpg"
        with patch("kie_video.client.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                upload_response
            ).encode()

            download_url = self.client.upload_image(image_path)

        self.assertEqual(download_url, "https://tempfile.test/sample.jpg")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://kieai.redpandaai.co/api/file-stream-upload")
        self.assertIn("multipart/form-data; boundary=", request.get_header("Content-type"))
        self.assertIn(b'name="uploadPath"\r\n\r\nimages/user-uploads', request.data)
        self.assertIn(b'name="file"; filename="sample.jpg"', request.data)
        self.assertIn(b"Content-Type: image/jpeg", request.data)
        self.assertTrue(image_path.read_bytes().startswith(b"\xff\xd8\xff"))
        self.assertIn(image_path.read_bytes(), request.data)

    def test_upload_image_bytes_supports_web_uploaded_file_content(self) -> None:
        upload_response = {
            "code": 200,
            "data": {"downloadUrl": "https://tempfile.test/uploaded-sample.jpg"},
        }
        image_path = Path(__file__).parent / "fixtures" / "sample.jpg"
        with patch("kie_video.client.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                upload_response
            ).encode()

            download_url = self.client.upload_image_bytes(
                image_path.name,
                image_path.read_bytes(),
            )

        self.assertEqual(download_url, "https://tempfile.test/uploaded-sample.jpg")
        request = urlopen.call_args.args[0]
        self.assertIn(b'name="file"; filename="sample.jpg"', request.data)
        self.assertIn(image_path.read_bytes(), request.data)


class KieVideoCliTests(unittest.TestCase):
    def test_local_image_is_uploaded_before_video_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "local.png"
            image_path.write_bytes(b"png-data")
            output_path = Path(temp_dir) / "video.mp4"
            with (
                patch.dict("os.environ", {"KIE_API_KEY": "test-key"}),
                patch("kie_video.cli.KieClient") as client_class,
            ):
                client = client_class.return_value
                client.upload_image.return_value = "https://tempfile.test/uploaded.png"

                def create_task_after_upload(*args: object) -> str:
                    self.assertEqual(client.upload_image.call_count, 1)
                    return "task-123"

                client.create_task.side_effect = create_task_after_upload
                client.wait_for_completion.return_value = "https://cdn.test/video.mp4"
                client.download_video.return_value = output_path

                exit_code = main(
                    [
                        "--image-path",
                        str(image_path),
                        "--prompt",
                        "A gentle camera pan",
                        "--output",
                        str(output_path),
                    ]
                )

        self.assertEqual(exit_code, 0)
        client.upload_image.assert_called_once_with(image_path)
        client.create_task.assert_called_once_with(
            "grok-imagine-video-1-5-preview",
            {
                "duration": 8,
                "resolution": "480p",
                "nsfw_checker": False,
                "prompt": "A gentle camera pan",
                "image_urls": ["https://tempfile.test/uploaded.png"],
            },
        )

    def test_image_url_uses_video_15_model_and_input_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "animated.mp4"
            with (
                patch.dict("os.environ", {"KIE_API_KEY": "test-key"}),
                patch("kie_video.cli.KieClient") as client_class,
            ):
                client_class.return_value.create_task.return_value = "task-123"
                client_class.return_value.wait_for_completion.return_value = (
                    "https://cdn.test/video.mp4"
                )
                client_class.return_value.download_video.return_value = output_path

                exit_code = main(
                    [
                        "--image-url",
                        "https://example.com/image.webp",
                        "--prompt",
                        "A slow camera pan",
                        "--output",
                        str(output_path),
                    ]
                )

        self.assertEqual(exit_code, 0)
        client_class.return_value.create_task.assert_called_once_with(
            "grok-imagine-video-1-5-preview",
            {
                "image_urls": ["https://example.com/image.webp"],
                "duration": 8,
                "resolution": "480p",
                "nsfw_checker": False,
                "prompt": "A slow camera pan",
            },
        )

    def test_text_prompt_uses_video_15_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "text.mp4"
            with (
                patch.dict("os.environ", {"KIE_API_KEY": "test-key"}),
                patch("kie_video.cli.KieClient") as client_class,
            ):
                client_class.return_value.create_task.return_value = "task-123"
                client_class.return_value.wait_for_completion.return_value = (
                    "https://cdn.test/video.mp4"
                )
                client_class.return_value.download_video.return_value = output_path

                exit_code = main(
                    [
                        "--prompt",
                        "A cinematic sunrise",
                        "--output",
                        str(output_path),
                    ]
                )

        self.assertEqual(exit_code, 0)
        client_class.return_value.create_task.assert_called_once_with(
            "grok-imagine-video-1-5-preview",
            {
                "duration": 8,
                "resolution": "480p",
                "nsfw_checker": False,
                "prompt": "A cinematic sunrise",
                "aspect_ratio": "9:16",
            },
        )

    def test_multiple_images_send_selected_aspect_ratio_and_filter_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "multi.mp4"
            with (
                patch.dict("os.environ", {"KIE_API_KEY": "test-key"}),
                patch("kie_video.cli.KieClient") as client_class,
            ):
                client_class.return_value.create_task.return_value = "task-123"
                client_class.return_value.wait_for_completion.return_value = (
                    "https://cdn.test/video.mp4"
                )
                client_class.return_value.download_video.return_value = output_path

                exit_code = main(
                    [
                        "--image-url",
                        "https://example.com/first.jpg",
                        "--image-url",
                        "https://example.com/second.png",
                        "--aspect-ratio",
                        "16:9",
                        "--nsfw-checker",
                        "--output",
                        str(output_path),
                    ]
                )

        self.assertEqual(exit_code, 0)
        client_class.return_value.create_task.assert_called_once_with(
            "grok-imagine-video-1-5-preview",
            {
                "duration": 8,
                "resolution": "480p",
                "nsfw_checker": True,
                "image_urls": [
                    "https://example.com/first.jpg",
                    "https://example.com/second.png",
                ],
                "aspect_ratio": "16:9",
            },
        )


if __name__ == "__main__":
    unittest.main()
