"""Small committed extracts from the saved Level Shoes Miu Miu PDP fixture."""

MIUMIU_PRODUCT_DETAILS = {
    "image": {
        "url": (
            "https://assets.levelshoes.com/cdn-cgi/image/"
            "width=720,height=1008,quality=85,format=webp/media/catalog/product/"
            "5/b/5bp078olo2bd8f0d30v_1.jpg?ts=20250506031705"
        ),
    },
    "imagePreviewGallery": [
        {
            "url": (
                "https://assets.levelshoes.com/cdn-cgi/image/"
                "width=720,height=1008,quality=85,format=webp/media/catalog/product/"
                "5/b/5bp078olo2bd8f0d30v_1.jpg?ts=20250506031705"
            ),
        },
        {
            "url": (
                "https://assets.levelshoes.com/cdn-cgi/image/"
                "width=720,height=1008,quality=85,format=webp/media/catalog/product/"
                "5/b/5bp078olo2bd8f0d30v_4.jpg?ts=20250506031708"
            ),
        },
        {
            "url": (
                "https://assets.levelshoes.com/cdn-cgi/image/"
                "width=720,height=1008,quality=85,format=webp/media/catalog/product/"
                "5/b/5bp078olo2bd8f0d30v_5.jpg?ts=20250506031710"
            ),
        },
        {
            "url": (
                "https://assets.levelshoes.com/cdn-cgi/image/"
                "width=720,height=1008,quality=85,format=webp/media/catalog/product/"
                "5/b/5bp078olo2bd8f0d30v_6.jpg?ts=20250506031712"
            ),
        },
    ],
}

MIUMIU_EXPECTED_IMAGE_URLS = [
    image["url"] for image in MIUMIU_PRODUCT_DETAILS["imagePreviewGallery"]
]
