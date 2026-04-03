from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('quiz.urls')), # Sends traffic to your app
]

handler404 = 'quiz.views.custom_404_view'