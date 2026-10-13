from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """标准分页类，支持前端传 page_size 参数"""
    page_size_query_param = 'page_size'
    max_page_size = 100
