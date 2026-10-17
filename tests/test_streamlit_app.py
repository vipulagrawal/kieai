from __future__ import annotations

import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class StreamlitAppTests(unittest.TestCase):
    def test_login_is_required_before_showing_video_generator(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        with patch.dict(os.environ, {"APP_PASSWORD": ""}):
            app = AppTest.from_file(str(app_path)).run()

        self.assertEqual(app.exception, [])
        self.assertTrue(any("App login is not configured" in item.value for item in app.error))
        self.assertFalse(any(item.label == "Kie.ai API key" for item in app.text_input))

    def test_login_rejects_incorrect_password_and_clears_input(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        with patch.dict(os.environ, {"APP_PASSWORD": "correct-password"}):
            app = AppTest.from_file(str(app_path)).run()
            app.text_input[0].set_value("incorrect-password")
            app.button[0].click().run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.session_state["app_password_input"], "")
        self.assertTrue(any("Incorrect password" in item.value for item in app.error))
        self.assertFalse(any(item.label == "Kie.ai API key" for item in app.text_input))

    def test_logout_returns_to_login_screen(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        with patch.dict(os.environ, {"APP_PASSWORD": "test-login-password"}):
            app = AppTest.from_file(str(app_path)).run()
            app.text_input[0].set_value("test-login-password")
            app.button[0].click().run()
            app.button[0].click().run()

        self.assertEqual(app.exception, [])
        self.assertFalse(app.session_state["authenticated"])
        self.assertEqual([item.label for item in app.text_input], ["App password"])

    def test_api_key_widget_is_cleared_after_form_submission(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        log_output = io.StringIO()
        handler = logging.StreamHandler(log_output)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            with patch.dict(os.environ, {"APP_PASSWORD": "test-login-password"}):
                app = AppTest.from_file(str(app_path)).run()
                app.text_input[0].set_value("test-login-password")
                app.button[0].click().run()
                app.text_input[0].set_value("test-secret-value")
                app.button[1].click().run()
        finally:
            root_logger.removeHandler(handler)
            handler.close()

        self.assertEqual(app.exception, [])
        self.assertTrue(app.session_state["authenticated"])
        self.assertEqual(app.session_state["kie_api_key_input"], "")
        self.assertNotIn("_submitted_api_key", app.session_state)
        self.assertTrue(any("Enter a prompt or upload" in item.value for item in app.error))
        self.assertNotIn("test-secret-value", log_output.getvalue())

    def test_direct_image_url_is_sent_to_grok_api(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "video.mp4"
            with patch("kie_video.client.KieClient") as client_class:
                client = client_class.return_value
                client.create_task.return_value = "task-123"
                client.wait_for_completion.return_value = "https://cdn.test/video.mp4"
                client.download_video.side_effect = lambda _url, destination: (
                    Path(destination).write_bytes(b"video-data") and Path(destination)
                )

                with patch.dict(os.environ, {"APP_PASSWORD": "test-login-password"}):
                    app = AppTest.from_file(str(app_path)).run()
                    app.text_input[0].set_value("test-login-password")
                    app.button[0].click().run()
                    app.text_input[0].set_value("test-api-key")
                    app.text_area[0].set_value("Animate this image")
                    app.text_input[1].set_value("https://example.com/image.jpg")
                    app.button[1].click().run()

        self.assertEqual(app.exception, [])
        client.create_task.assert_called_once_with(
            "grok-imagine-video-1-5-preview",
            {
                "duration": 8,
                "resolution": "480p",
                "nsfw_checker": False,
                "prompt": "Animate this image",
                "image_urls": ["https://example.com/image.jpg"],
            },
        )

    def test_invalid_image_url_is_rejected_before_api_request(self) -> None:
        app_path = Path(__file__).parents[1] / "streamlit_app.py"
        with patch("kie_video.client.KieClient") as client_class:
            with patch.dict(os.environ, {"APP_PASSWORD": "test-login-password"}):
                app = AppTest.from_file(str(app_path)).run()
                app.text_input[0].set_value("test-login-password")
                app.button[0].click().run()
                app.text_input[0].set_value("test-api-key")
                app.text_area[0].set_value("Animate this image")
                app.text_input[1].set_value("file:///local/image.jpg")
                app.button[1].click().run()

        self.assertEqual(app.exception, [])
        self.assertTrue(any("HTTP or HTTPS" in item.value for item in app.error))
        client_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
