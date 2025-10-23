"""
Core views for Blik application
"""
from django.http import JsonResponse
from django.shortcuts import render


def health_check(request):
    """Health check endpoint for monitoring"""
    return JsonResponse({
        'status': 'healthy',
        'service': 'blik',
        'version': '0.1.0'
    })


def home(request):
    """Home page"""
    return render(request, 'home.html')
