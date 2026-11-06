from unittest import mock

from apps.customers.models import OtpCode, User, normalize_phone

from .base import BaseTestCase


class PhoneTests(BaseTestCase):
    def test_normalize(self):
        self.assertEqual(normalize_phone("+998 (90) 123-45-67"), "998901234567")
        self.assertEqual(normalize_phone("901234567"), "998901234567")
        with self.assertRaises(ValueError):
            normalize_phone("12345")


class OtpFlowTests(BaseTestCase):
    @mock.patch("apps.customers.views.send_sms")
    def test_login_creates_user_and_returns_tokens(self, send):
        c = self.api()
        r = c.post("/api/auth/otp/request/", {"phone": "90 123 45 67"})
        self.assertEqual(r.status_code, 200)
        code = send.call_args[0][1].split()[-1]
        self.assertEqual(c.post("/api/auth/otp/request/", {"phone": "901234567"}).status_code, 429)

        self.assertEqual(c.post("/api/auth/otp/verify/", {"phone": "901234567", "code": "0000" if code != "0000" else "1111"}).status_code, 400)
        r = c.post("/api/auth/otp/verify/", {"phone": "901234567", "code": code})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_new"])
        self.assertTrue(User.objects.filter(phone="998901234567").exists())
        # code is single-use
        self.assertEqual(c.post("/api/auth/otp/verify/", {"phone": "901234567", "code": code}).status_code, 400)

        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(c.patch("/api/auth/me/", {"first_name": "Камол"}).data["first_name"], "Камол")

    def test_attempts_limited(self):
        _, code = OtpCode.issue("998901234567")
        wrong = "0000" if code != "0000" else "1111"
        for _ in range(5):
            self.assertFalse(OtpCode.verify("998901234567", wrong))
        self.assertFalse(OtpCode.verify("998901234567", code))  # locked after 5 failures


class ProfileTests(BaseTestCase):
    def test_addresses_are_private(self):
        from . import factories as f

        a, b = f.customer("998901111111"), f.customer("998902222222")
        r = self.api(a).post("/api/auth/addresses/", {"address": "Дом", "lat": "41.3", "lng": "69.2"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(self.api(b).get("/api/auth/addresses/").data), 0)
