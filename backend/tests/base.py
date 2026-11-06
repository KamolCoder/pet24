import shutil
import tempfile

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

_MEDIA = tempfile.mkdtemp(prefix="pet24-test-media-")


@override_settings(MEDIA_ROOT=_MEDIA, COURIER_PROVIDER="manual", SECRET_KEY="test-secret-key-for-unit-tests-only-0123456789")
class BaseTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def api(self, user=None) -> APIClient:
        client = APIClient()
        if user:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client
