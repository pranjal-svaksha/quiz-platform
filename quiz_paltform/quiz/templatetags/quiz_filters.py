# yourapp/templatetags/quiz_filters.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, [])

@register.filter
def make_list(value):
    """Split comma-separated string into list"""
    return [x.strip() for x in value.split(',')]