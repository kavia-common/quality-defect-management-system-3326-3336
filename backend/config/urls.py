"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.views.decorators.csrf import csrf_exempt

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
]

openapi_tags = [
    {"name": "health", "description": "Service health check"},
    {"name": "defects", "description": "Defect CRUD, workflow transitions, overdue lists, CSV export"},
    {"name": "analysis", "description": "5-Why root cause analysis endpoints"},
    {"name": "actions", "description": "Corrective action CRUD and overdue queries"},
    {"name": "dashboard", "description": "Dashboard aggregate metrics for UI"},
    {"name": "export", "description": "CSV export endpoints"},
]

schema_view = get_schema_view(
   openapi.Info(
      title="Quality Defect Management API",
      default_version='v1',
      description="REST API for tracking quality defects, root cause (5-Why), corrective actions, workflow, metrics, and export.",
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

def get_full_url(request):
    scheme = request.scheme
    host = request.get_host()
    forwarded_port = request.META.get("HTTP_X_FORWARDED_PORT")

    if ':' not in host and forwarded_port:
        host = f"{host}:{forwarded_port}"

    return f"{scheme}://{host}"

@csrf_exempt
def dynamic_schema_view(request, *args, **kwargs):
    url = get_full_url(request)
    # NOTE:
    # drf-yasg's get_schema_view does not support a `tags=` kwarg (varies by version),
    # and passing it causes `/docs/` to 500 with:
    #   TypeError: get_schema_view() got an unexpected keyword argument 'tags'
    # Keeping the dynamic `url=` behavior for correct server URL generation behind proxies.
    view = get_schema_view(
        openapi.Info(
            title="Quality Defect Management API",
            default_version="v1",
            description="REST API documentation (Swagger UI).",
        ),
        public=True,
        url=url,
        permission_classes=(permissions.AllowAny,),
    )
    return view.with_ui("swagger", cache_timeout=0)(request)

urlpatterns += [
    re_path(r"^docs/$", dynamic_schema_view, name="schema-swagger-ui"),
    re_path(r"^redoc/$", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    re_path(r"^swagger\.json$", schema_view.without_ui(cache_timeout=0), name="schema-json"),
]