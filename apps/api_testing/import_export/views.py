"""
API import/export views.
"""
import logging
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import ApiCollection, ApiProject, ApiRequest
from . import (
    CurlParser,
    HARParser,
    OpenAPIExporter,
    OpenAPIParser,
    PostmanExporter,
    PostmanParser,
    SAZParser,
    SwaggerExporter,
)
from .header_utils import normalize_import_headers

logger = logging.getLogger(__name__)


def _normalize_collection_name(name):
    normalized = (name or "Imported").strip()
    return normalized or "Imported"


def _normalize_request_name(name):
    normalized = (name or "").strip()
    return normalized or "Imported Request"


def _normalize_request_method(method):
    normalized = (method or "GET").strip().upper()
    return normalized or "GET"


def _normalize_request_url(url):
    normalized = (url or "").strip()
    if not normalized:
        return ""

    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        path = parsed.path or "/"
        return f"{path}?{parsed.query}" if parsed.query else path

    return normalized


def _normalize_request_headers(headers):
    return normalize_import_headers(headers)


def _get_accessible_project(user, project_id):
    return (
        ApiProject.objects.filter(id=project_id)
        .filter(Q(owner=user) | Q(members=user))
        .distinct()
        .first()
    )


def _build_request_payload(req_data, order):
    name = _normalize_request_name(req_data.get("name"))
    return {
        "name": name[:200],
        "description": req_data.get("description", ""),
        "method": _normalize_request_method(req_data.get("method")),
        "url": _normalize_request_url(req_data.get("url")),
        "headers": _normalize_request_headers(req_data.get("headers")),
        "params": req_data.get("params", {}),
        "body": req_data.get("body", {}),
        "order": order,
    }


def _find_existing_request(collection, req_data):
    if collection is None:
        return None

    method = _normalize_request_method(req_data.get("method"))
    url = _normalize_request_url(req_data.get("url"))
    name = _normalize_request_name(req_data.get("name"))[:200]

    queryset = ApiRequest.objects.filter(collection=collection, method=method)
    if url:
        return queryset.filter(url=url).order_by("id").first()

    return queryset.filter(name=name, url="").order_by("id").first()


def _find_preview_target_collection(*, project, target_collection, col_data):
    if not project:
        return None
    if target_collection:
        return target_collection

    collection_name = _normalize_collection_name(col_data.get("name"))
    return (
        ApiCollection.objects.filter(
            project=project,
            parent=None,
            name=collection_name,
        )
        .order_by("id")
        .first()
    )


def _annotate_preview_result(*, result, project, target_collection):
    collections = result.get("collections") or []
    skipped_existing_requests = 0
    importable_requests = 0

    for col_data in collections:
        preview_target_collection = _find_preview_target_collection(
            project=project,
            target_collection=target_collection,
            col_data=col_data,
        )
        existing_request_count = 0

        col_data["_target_collection_id"] = getattr(preview_target_collection, "id", None)
        col_data["_target_collection_exists"] = preview_target_collection is not None

        for req_data in col_data.get("requests", []):
            existing_request = _find_existing_request(preview_target_collection, req_data)
            exists = existing_request is not None

            req_data["_exists"] = exists
            req_data["_disabled"] = exists
            req_data["_selected"] = not exists
            req_data["_exists_message"] = "当前接口已存在，忽略导入" if exists else ""

            if exists:
                existing_request_count += 1
                skipped_existing_requests += 1
            else:
                importable_requests += 1

        col_data["_existing_request_count"] = existing_request_count
        col_data["_importable_request_count"] = max(
            0,
            len(col_data.get("requests", [])) - existing_request_count,
        )
        col_data["_selected"] = col_data["_importable_request_count"] > 0

    result["skipped_existing_requests"] = skipped_existing_requests
    result["importable_requests"] = importable_requests
    return result


def _resolve_import_collection(*, project, target_collection, col_data):
    if target_collection:
        return target_collection, False

    collection_name = _normalize_collection_name(col_data.get("name"))
    existing = (
        ApiCollection.objects.filter(
            project=project,
            parent=None,
            name=collection_name,
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing, False

    collection = ApiCollection.objects.create(
        name=collection_name,
        description=col_data.get("description", ""),
        project=project,
        parent=None,
        order=ApiCollection.objects.filter(project=project, parent=None).count(),
    )
    return collection, True


class ImportPreviewView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        format_type = request.data.get("format", "")
        project_id = request.data.get("project_id")
        target_collection_id = request.data.get("target_collection_id")
        content = ""
        file = None

        project = None
        target_collection = None
        if project_id:
            project = _get_accessible_project(request.user, project_id)
            if not project:
                return Response({"error": "目标项目不存在或无权限"}, status=404)
            if target_collection_id:
                target_collection = ApiCollection.objects.filter(
                    id=target_collection_id,
                    project=project,
                ).first()
                if not target_collection:
                    return Response({"error": "目标集合不存在"}, status=404)

        if format_type == "curl":
            content = request.data.get("content", "")
            if not content:
                return Response({"error": "请输入 cURL 命令"}, status=400)
        elif format_type == "saz":
            file = request.FILES.get("file")
            if not file:
                return Response({"error": "请上传文件"}, status=400)
            content = file.read()
        else:
            file = request.FILES.get("file")
            if not file:
                return Response({"error": "请上传文件"}, status=400)
            raw_bytes = file.read()
            try:
                content = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw_bytes.decode("utf-8", errors="ignore")

        parser_map = {
            "openapi": OpenAPIParser,
            "swagger": OpenAPIParser,
            "postman": PostmanParser,
            "curl": CurlParser,
            "har": HARParser,
            "saz": SAZParser,
        }

        parser_cls = parser_map.get(format_type)
        if not parser_cls:
            return Response({"error": f"不支持的格式: {format_type}"}, status=400)

        try:
            parser = parser_cls()
            parser_filename = getattr(file, "name", "") if format_type != "curl" else ""
            result = parser.parse(content, filename=parser_filename)
            if project:
                result = _annotate_preview_result(
                    result=result,
                    project=project,
                    target_collection=target_collection,
                )
            return Response(result)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("Import preview failed: %s", exc)
            return Response({"error": f"解析失败: {str(exc)}"}, status=500)


class ImportConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        project_id = request.data.get("project_id")
        target_collection_id = request.data.get("target_collection_id")
        collections_data = request.data.get("collections", [])

        if not project_id:
            return Response({"error": "请选择目标项目"}, status=400)

        project = _get_accessible_project(request.user, project_id)
        if not project:
            return Response({"error": "项目不存在或无权限"}, status=404)

        target_collection = None
        if target_collection_id:
            target_collection = ApiCollection.objects.filter(
                id=target_collection_id,
                project=project,
            ).first()
            if not target_collection:
                return Response({"error": "目标集合不存在"}, status=404)

        created_collections = 0
        created_requests = 0
        skipped_requests = 0

        try:
            with transaction.atomic():
                for col_data in collections_data:
                    collection, created = _resolve_import_collection(
                        project=project,
                        target_collection=target_collection,
                        col_data=col_data,
                    )
                    if created:
                        created_collections += 1

                    next_order = ApiRequest.objects.filter(collection=collection).count()
                    for req_data in col_data.get("requests", []):
                        if _find_existing_request(collection, req_data):
                            skipped_requests += 1
                            continue

                        ApiRequest.objects.create(
                            collection=collection,
                            created_by=request.user,
                            **_build_request_payload(req_data, next_order),
                        )
                        created_requests += 1
                        next_order += 1

            return Response(
                {
                    "message": (
                        f"导入成功：{created_collections} 个集合，"
                        f"新增 {created_requests} 个接口，"
                        f"忽略 {skipped_requests} 个已存在接口"
                    ),
                    "created_collections": created_collections,
                    "created_requests": created_requests,
                    "skipped_requests": skipped_requests,
                }
            )
        except Exception as exc:
            logger.exception("Import confirm failed: %s", exc)
            return Response({"error": f"导入失败: {str(exc)}"}, status=500)


class ExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        format_type = request.query_params.get("export_format", "openapi")
        collection_id = request.query_params.get("collection_id")

        try:
            project = ApiProject.objects.get(id=project_id)
        except ApiProject.DoesNotExist:
            return Response({"error": "项目不存在"}, status=404)

        collections = ApiCollection.objects.filter(project=project).order_by("order")
        requests = ApiRequest.objects.filter(collection__project=project).select_related("collection").order_by(
            "collection__order", "order"
        )

        if collection_id:
            collections = collections.filter(id=collection_id)
            requests = requests.filter(collection_id=collection_id)

        if format_type == "openapi":
            exporter = OpenAPIExporter()
            result = exporter.export(project, collections, requests)
            response = JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})
            response["Content-Disposition"] = f'attachment; filename="{project.name}_openapi.json"'
            return response
        if format_type == "swagger":
            exporter = SwaggerExporter()
            result = exporter.export(project, collections, requests)
            response = JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})
            response["Content-Disposition"] = f'attachment; filename="{project.name}_swagger.json"'
            return response
        if format_type == "postman":
            exporter = PostmanExporter()
            result = exporter.export(project, collections, requests)
            response = JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})
            response["Content-Disposition"] = f'attachment; filename="{project.name}_postman.json"'
            return response

        return Response({"error": f"不支持的导出格式: {format_type}"}, status=400)
