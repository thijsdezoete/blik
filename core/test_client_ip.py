from django.test import RequestFactory, SimpleTestCase, override_settings

from core.client_ip import client_ip


class ClientIpTests(SimpleTestCase):
    def request(self, **meta):
        return RequestFactory().get("/", REMOTE_ADDR="10.0.1.20", **meta)

    @override_settings(TRUSTED_CLIENT_IP_HEADER="")
    def test_setting_empty_ignores_header(self):
        request = self.request(HTTP_CF_CONNECTING_IP="203.0.113.7")
        self.assertEqual(client_ip(request), "10.0.1.20")

    @override_settings(TRUSTED_CLIENT_IP_HEADER="HTTP_CF_CONNECTING_IP")
    def test_setting_set_uses_header(self):
        request = self.request(HTTP_CF_CONNECTING_IP=" 203.0.113.7 ")
        self.assertEqual(client_ip(request), "203.0.113.7")

    @override_settings(TRUSTED_CLIENT_IP_HEADER="HTTP_CF_CONNECTING_IP")
    def test_missing_header_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.request()), "10.0.1.20")

    @override_settings(TRUSTED_CLIENT_IP_HEADER="HTTP_CF_CONNECTING_IP")
    def test_list_takes_first_entry(self):
        request = self.request(HTTP_CF_CONNECTING_IP="203.0.113.7, 10.0.1.31")
        self.assertEqual(client_ip(request), "203.0.113.7")
