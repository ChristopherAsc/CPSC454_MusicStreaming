from django.shortcuts import render
from django.http import HttpResponse

# Create your views here.

def index(request):
    return HttpResponse("You're at the index.")

def test(request):
    return HttpResponse("This is the test")

