from django.urls import path
from . import views


# make the url patterns there, the first parameter is what's going in the URL so dont have a / at the start. 
# naming convention if you want to get specific should be  (route)/ with the / after the route if needed. Route name alone works just fine.

urlpatterns = [
    path("", views.index, name="index"),
    path("test", views.test, name="test" )
]
