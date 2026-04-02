from django.contrib import admin
from django.urls import path, include  # <-- Don't forget to import 'include' here!

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # This tells Django: "Any web traffic that comes in, send it to my app's urls.py"
    path('', include('quiz.urls')),
]