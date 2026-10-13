from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.api_testing.models import ApiCollection, ApiProject, ApiRequest, TestSuite, TestSuiteRequest
from apps.api_testing.utils import build_suite_request_runtime_data


User = get_user_model()


class ImportConfirmViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="import_tester",
            password="test123456",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.project = ApiProject.objects.create(
            name="Import Project",
            description="",
            project_type="HTTP",
            status="active",
            owner=self.user,
        )
        self.project.members.add(self.user)

        self.preview_url = "/api/api-testing/import/preview/"
        self.confirm_url = "/api/api-testing/import/confirm/"

    def test_preview_marks_existing_request_as_skipped(self):
        collection = ApiCollection.objects.create(
            project=self.project,
            name="User APIs",
            description="",
            order=0,
        )
        ApiRequest.objects.create(
            collection=collection,
            name="Login API",
            description="old request",
            method="POST",
            url="/api/login",
            headers=[],
            params={},
            body={},
            created_by=self.user,
            order=0,
        )

        response = self.client.post(
            self.preview_url,
            {
                "format": "curl",
                "content": "curl -X POST 'https://example.com/api/login'",
                "project_id": self.project.id,
                "target_collection_id": collection.id,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["skipped_existing_requests"], 1)
        request_data = response.data["collections"][0]["requests"][0]
        self.assertTrue(request_data["_exists"])
        self.assertTrue(request_data["_disabled"])
        self.assertFalse(request_data["_selected"])
        self.assertEqual(request_data["_exists_message"], "当前接口已存在，忽略导入")

    def test_confirm_skips_existing_request_when_method_and_url_match(self):
        collection = ApiCollection.objects.create(
            project=self.project,
            name="User APIs",
            description="old desc",
            order=0,
        )
        existing_request = ApiRequest.objects.create(
            collection=collection,
            name="Old Login",
            description="old request",
            method="POST",
            url="/api/login",
            headers=[{"key": "X-Old", "value": "1", "enabled": True}],
            params={"page": 1},
            body={"type": "json", "data": {"old": True}},
            created_by=self.user,
            order=0,
        )

        response = self.client.post(
            self.confirm_url,
            {
                "project_id": self.project.id,
                "collections": [
                    {
                        "name": "User APIs",
                        "description": "new desc",
                        "requests": [
                            {
                                "name": "Login API",
                                "description": "should be skipped",
                                "method": "post",
                                "url": "/api/login",
                                "headers": {"Authorization": "Bearer token"},
                                "params": {"source": "import"},
                                "body": {"type": "json", "data": {"username": "demo"}},
                            }
                        ],
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created_collections"], 0)
        self.assertEqual(response.data["created_requests"], 0)
        self.assertEqual(response.data["skipped_requests"], 1)

        self.assertEqual(ApiCollection.objects.filter(project=self.project, name="User APIs").count(), 1)
        self.assertEqual(ApiRequest.objects.filter(collection=collection).count(), 1)

        existing_request.refresh_from_db()
        self.assertEqual(existing_request.name, "Old Login")
        self.assertEqual(existing_request.description, "old request")
        self.assertEqual(existing_request.params, {"page": 1})

    def test_creates_new_request_when_url_differs(self):
        collection = ApiCollection.objects.create(
            project=self.project,
            name="Order APIs",
            description="",
            order=0,
        )
        ApiRequest.objects.create(
            collection=collection,
            name="Get Orders",
            description="",
            method="GET",
            url="/api/orders",
            headers=[],
            params={},
            body={},
            created_by=self.user,
            order=0,
        )

        response = self.client.post(
            self.confirm_url,
            {
                "project_id": self.project.id,
                "collections": [
                    {
                        "name": "Order APIs",
                        "requests": [
                            {
                                "name": "Get Order Detail",
                                "method": "GET",
                                "url": "/api/orders/1",
                                "headers": [],
                                "params": {},
                                "body": {},
                            }
                        ],
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created_collections"], 0)
        self.assertEqual(response.data["created_requests"], 1)
        self.assertEqual(response.data["skipped_requests"], 0)
        self.assertEqual(ApiRequest.objects.filter(collection=collection).count(), 2)


class DeleteDependencyGuardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dependency_guard",
            password="test123456",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.project = ApiProject.objects.create(
            name="Dependency Project",
            description="",
            project_type="HTTP",
            status="active",
            owner=self.user,
        )
        self.project.members.add(self.user)

        self.collection = ApiCollection.objects.create(
            project=self.project,
            name="User APIs",
            description="",
            order=0,
        )
        self.request = ApiRequest.objects.create(
            collection=self.collection,
            name="Login API",
            description="",
            method="POST",
            url="/api/login",
            headers=[],
            params={},
            body={},
            created_by=self.user,
            order=0,
        )
        self.suite = TestSuite.objects.create(
            project=self.project,
            name="登录回归",
            description="",
            created_by=self.user,
        )
        TestSuiteRequest.objects.create(
            test_suite=self.suite,
            request=self.request,
            order=0,
        )

    def _message_text(self, response):
        message = response.data["message"]
        if isinstance(message, list):
            return "\n".join(str(item) for item in message)
        return str(message)

    def test_delete_request_blocked_when_used_by_test_suite(self):
        response = self.client.delete(f"/api/api-testing/requests/{self.request.id}/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("当前接口已被自动化用例引用", self._message_text(response))
        self.assertEqual(response.data["dependency_type"], "api_test_suite")
        self.assertEqual(response.data["dependencies"]["suite_count"], 1)
        self.assertEqual(response.data["dependencies"]["request_count"], 1)
        self.assertEqual(response.data["dependencies"]["suites"][0]["name"], "登录回归")
        self.assertTrue(ApiRequest.objects.filter(id=self.request.id).exists())

    def test_delete_collection_blocked_when_nested_request_used_by_test_suite(self):
        child_collection = ApiCollection.objects.create(
            project=self.project,
            parent=self.collection,
            name="Child APIs",
            description="",
            order=1,
        )
        nested_request = ApiRequest.objects.create(
            collection=child_collection,
            name="Profile API",
            description="",
            method="GET",
            url="/api/profile",
            headers=[],
            params={},
            body={},
            created_by=self.user,
            order=0,
        )
        TestSuiteRequest.objects.create(
            test_suite=self.suite,
            request=nested_request,
            order=1,
        )

        response = self.client.delete(f"/api/api-testing/collections/{self.collection.id}/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("当前集合下的接口已被自动化用例引用", self._message_text(response))
        self.assertEqual(response.data["dependency_type"], "api_test_suite")
        self.assertEqual(response.data["dependencies"]["suite_count"], 1)
        self.assertEqual(response.data["dependencies"]["request_count"], 2)
        self.assertTrue(ApiCollection.objects.filter(id=self.collection.id).exists())


class TestSuiteRequestCompatibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="suite_request_tester",
            password="test123456",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.project = ApiProject.objects.create(
            name="Suite Project",
            description="",
            project_type="HTTP",
            status="active",
            owner=self.user,
        )
        self.project.members.add(self.user)

        self.collection = ApiCollection.objects.create(
            project=self.project,
            name="Auth APIs",
            description="",
            order=0,
        )
        self.request = ApiRequest.objects.create(
            collection=self.collection,
            name="Login API",
            description="",
            method="POST",
            url="/api/login",
            headers={"X-Env": "{{env}}"},
            params={"from": "base"},
            body={"type": "json", "data": {"username": "demo"}},
            pre_request_script="log('base pre')",
            post_request_script="log('base post')",
            assertions=[{"name": "状态码", "type": "status_code", "expected": 200}],
            extractors=[{"name": "token", "variable_name": "token", "type": "json_path", "expression": "$.token"}],
            created_by=self.user,
            order=0,
        )
        self.suite = TestSuite.objects.create(
            project=self.project,
            name="登录回归",
            description="",
            created_by=self.user,
        )

    def test_add_requests_allows_same_request_multiple_times(self):
        response = self.client.post(
            f"/api/api-testing/test-suites/{self.suite.id}/add-requests/",
            {
                "items": [
                    {"request_id": self.request.id},
                    {
                        "request_id": self.request.id,
                        "display_name": "第二次登录",
                        "request_overrides": {
                            "url": "/api/login/refresh",
                            "params": {"from": "second"},
                        },
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        suite_requests = list(TestSuiteRequest.objects.filter(test_suite=self.suite).order_by("order"))
        self.assertEqual(len(suite_requests), 2)
        self.assertEqual(suite_requests[0].request_id, self.request.id)
        self.assertEqual(suite_requests[1].request_id, self.request.id)
        self.assertEqual(suite_requests[1].display_name, "第二次登录")
        self.assertEqual(suite_requests[1].request_overrides["url"], "/api/login/refresh")

    def test_runtime_data_uses_step_overrides_but_keeps_old_fields(self):
        suite_request = TestSuiteRequest.objects.create(
            test_suite=self.suite,
            request=self.request,
            display_name="登录并刷新",
            order=0,
            request_overrides={
                "method": "PUT",
                "url": "/api/login/refresh",
                "headers": {"Authorization": "Bearer {{token}}"},
                "params": {"from": "override"},
                "body": {"type": "json", "data": {"username": "override"}},
                "pre_request_script": "log('override pre')",
                "post_request_script": "log('override post')",
                "assertions": [{"name": "状态码", "type": "status_code", "expected": 201}],
                "extractors": [{"name": "refresh_token", "variable_name": "refresh_token"}],
            },
        )

        runtime_data = build_suite_request_runtime_data(suite_request)

        self.assertEqual(runtime_data["name"], "登录并刷新")
        self.assertEqual(runtime_data["request_name"], "Login API")
        self.assertEqual(runtime_data["method"], "PUT")
        self.assertEqual(runtime_data["url"], "/api/login/refresh")
        self.assertEqual(runtime_data["headers"], {"Authorization": "Bearer {{token}}"})
        self.assertEqual(runtime_data["params"], {"from": "override"})
        self.assertEqual(runtime_data["body"], {"type": "json", "data": {"username": "override"}})
        self.assertEqual(runtime_data["pre_request_script"], "log('override pre')")
        self.assertEqual(runtime_data["post_request_script"], "log('override post')")
        self.assertEqual(runtime_data["assertions"][0]["expected"], 201)
        self.assertEqual(runtime_data["extract_variables"][0]["variable_name"], "refresh_token")
