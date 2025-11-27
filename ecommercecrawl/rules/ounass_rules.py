import json

def is_plp(response):
    try:
        data = json.loads(response.text)
    except Exception:
        return False

    return data.get("routeType") == "plp"

def get_max_pages(response):
    data = json.loads(response.text)
    return data['pagination']['totalPages']


def is_first_page(response):
    return False