import pytest
from scrapy.settings import Settings
from unittest.mock import MagicMock, patch
from scrapy.http import HtmlResponse, Request
from ecommercecrawl.spiders.farfetch_crawl import FFSpider
from pathlib import Path


# --- Mock HTML Payloads ---
# A simplified HTML structure for a Product Detail Page (PDP)
MOCK_PDP_HTML = """
<html>
    <body>
        <a data-testid="brand-name">CoolBrand</a>
        <h1 data-testid="product-name">Stylish T-Shirt</h1>
        <p data-testid="price">USD $100.00</p>
        <span data-testid="discount-price">80</span>
        <button data-testid="size-selector-sold-out">Sold Out</button>
        <span data-testid="new-season-tag">New Season</span>
        <img src="https://example.com/image.jpg" />
        <p>Some descriptive text.</p>
        <ol>
            <li>Home</li>
            <li>Clothing</li>
            <li>T-Shirts</li>
        </ol>
    </body>
</html>
"""

# A simplified HTML for a Product Listing Page (PLP)
MOCK_PLP_HTML = """
<html>
    <body>
        <a href="/product/1">Product 1</a>
        <a href="/product/2">Product 2</a>
        <p data-testid="pagination-component">Page 1 of 3</p>
    </body>
</html>
"""

class TestFFSpider:
    def test_start_requests_reads_path_from_settings(self, tmp_path):
        # prepare a small CSV with two URLs
        csv_file = tmp_path / "urls.csv"
        csv_file.write_text("http://example.com/a\nhttp://example.com/b\n")

        # provide settings with FARFETCH_URLS_PATH
        settings = Settings({'FARFETCH_URLS_PATH': str(csv_file)})

        spider = FFSpider()
        spider.settings = settings

        requests = list(spider.start_requests())
        assert [r.url for r in requests] == ["http://example.com/a", "http://example.com/b"]

    @patch('ecommercecrawl.rules.farfetch_rules.get_list_page_urls')
    @patch('ecommercecrawl.rules.farfetch_rules.get_max_page')
    def test_get_pages_orchestration_with_pagination(self, mock_get_max_page, mock_get_list_page_urls):
        """Test that get_pages correctly orchestrates calls when pagination exists."""
        spider = FFSpider()
        
        # Mock response to simulate that pagination was found
        mock_response = MagicMock()
        mock_response.url = "https://www.example.com/category"
        pagination_text = "Page 1 of 4"
        mock_response.xpath.return_value.get.return_value = pagination_text

        # Configure mocks for rule functions
        mock_get_max_page.return_value = 4
        expected_urls = [
            "https://www.example.com/category",
            "https://www.example.com/category?page=2",
            "https://www.example.com/category?page=3",
            "https://www.example.com/category?page=4"
        ]
        mock_get_list_page_urls.return_value = expected_urls

        # Call the method
        result = spider.get_pages(mock_response)

        # Assertions
        mock_get_max_page.assert_called_once_with(pagination_text)
        mock_get_list_page_urls.assert_called_once_with(mock_response.url, 4)
        assert result == expected_urls

    @patch('ecommercecrawl.rules.farfetch_rules.get_list_page_urls')
    @patch('ecommercecrawl.rules.farfetch_rules.get_max_page')
    def test_get_pages_orchestration_no_pagination(self, mock_get_max_page, mock_get_list_page_urls):
        """Test that get_pages returns an empty list when no pagination is found."""
        spider = FFSpider()

        # Mock response to simulate that pagination was NOT found
        mock_response = MagicMock()
        mock_response.xpath.return_value.get.return_value = None # Simulate not finding pagination

        # Call the method
        result = spider.get_pages(mock_response)

        # Assertions
        assert result == []
        mock_get_max_page.assert_not_called()
        mock_get_list_page_urls.assert_not_called()

    def test_populate_pdp_data(self):
        """
        Tests the _populate_pdp_data method to ensure it correctly extracts
        data from a known HTML response. This test is independent of the live website.
        """

        # Instantiate the spider
        spider = FFSpider()
        # Create a mock URL and response
        test_url = "https://www.farfetch.com/uk/shopping/men/coolbrand/items.aspx"
        mock_response = HtmlResponse(url=test_url, body=MOCK_PDP_HTML, encoding='utf-8')

        # --- Mock the rules and xpaths to isolate the spider's logic ---
        # We assume the rules and xpaths are correct and test them separately.
        # Here, we are testing if _populate_pdp_data uses them correctly.
        with patch('ecommercecrawl.spiders.farfetch_crawl.rules') as mock_rules:
            # Configure mocks to return expected values from the fake HTML
            mock_rules.get_country.return_value = 'uk'
            mock_rules.get_portal_itemid.return_value = '12345'
            mock_rules.get_gender.return_value = 'men'
            mock_rules.get_price_and_currency.return_value = ('100.00', 'USD')
            mock_rules.get_category_from_breadcrumbs.return_value = 'Clothing'
            mock_rules.get_subcategory_from_breadcrumbs.return_value = 'T-Shirts'
            
            # Make the new rule functions use the mock response
            mock_rules.get_brand.return_value = "CoolBrand"
            mock_rules.get_product_name.return_value = "Stylish T-Shirt"
            mock_rules.get_discount.return_value = "80"
            mock_rules.is_sold_out.return_value = True
            mock_rules.get_primary_label.return_value = "New Season"
            mock_rules.get_image_url.return_value = "https://example.com/image.jpg"
            mock_rules.get_text.return_value = ["Some descriptive text."]

            # Call the method under test
            data = spider._populate_pdp_data(mock_response)

            # --- Assertions ---
            # Check that the data dictionary is populated correctly
            assert data['site'] == 'farfetch'
            assert data['country'] == 'uk'
            assert data['brand'] == 'CoolBrand'
            assert data['product_name'] == 'Stylish T-Shirt'
            assert data['price'] == '100.00'
            assert data['currency'] == 'USD'
            assert data['sold_out'] is True
            assert data['category'] == 'Clothing'
            assert data['image_url'] == 'https://example.com/image.jpg'

    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.download_images')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.save_to_csv')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.ensure_dir')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.build_output_basename')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider._populate_pdp_data')
    def test_parse_pdp(self, mock_populate_pdp_data, mock_build_output_basename,
                       mock_ensure_dir, mock_save_to_csv, mock_download_images):
        """
        Tests the parse_pdp method to ensure it correctly orchestrates
        data extraction, persistence, and image downloading.
        """
        spider = FFSpider()
        mock_response = MagicMock()
        mock_response.url = "https://www.farfetch.com/item/12345.aspx"

        # Mock return values for internal methods
        mock_populate_pdp_data.return_value = {
            'crawl_date': '2024-01-01',
            'image_url': 'https://example.com/image.jpg'
        }
        mock_build_output_basename.return_value = '/path/to/output/farfetch_2024-01-01'

        # Call the method under test
        list(spider.parse_pdp(mock_response))  # Convert generator to list to ensure all yields are processed

        # Assertions
        mock_populate_pdp_data.assert_called_once_with(mock_response)
        mock_build_output_basename.assert_called_once_with('output', 'farfetch', '2024-01-01')
        mock_ensure_dir.assert_called_once_with('output')
        mock_save_to_csv.assert_called_once_with('/path/to/output/farfetch_2024-01-01', {
            'crawl_date': '2024-01-01',
            'image_url': 'https://example.com/image.jpg'
        })
        mock_download_images.assert_called_once_with('2024-01-01', mock_response.url, 'https://example.com/image.jpg')

    @patch('ecommercecrawl.spiders.farfetch_crawl.rules')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.ensure_dir')
    def test_download_images_single_url(self, mock_ensure_dir, mock_rules):
        """
        Tests download_images with a single image URL.
        """
        spider = FFSpider()
        date_string = "2024-01-01"
        pdp_url = "https://www.farfetch.com/item/12345.aspx"
        image_field = "https://example.com/image1.jpg"
        
        mock_rules.get_pdp_subfolder.return_value = "12345"

        requests = list(spider.download_images(date_string, pdp_url, image_field))

        mock_ensure_dir.assert_called_once_with('output/images/farfetch/2024-01-01/12345')
        mock_rules.get_pdp_subfolder.assert_called_once_with(pdp_url)
        assert len(requests) == 1
        assert requests[0].url == image_field
        assert requests[0].callback == spider.save_image
        assert requests[0].meta['image_dir'] == 'output/images/farfetch/2024-01-01/12345'

    @patch('ecommercecrawl.spiders.farfetch_crawl.rules')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.ensure_dir')
    def test_download_images_multiple_urls(self, mock_ensure_dir, mock_rules):
        """
        Tests download_images with multiple image URLs.
        """
        spider = FFSpider()
        date_string = "2024-01-01"
        pdp_url = "https://www.farfetch.com/item/12345.aspx"
        image_field = ["https://example.com/image1.jpg", "https://example.com/image2.jpg"]

        mock_rules.get_pdp_subfolder.return_value = "12345"

        requests = list(spider.download_images(date_string, pdp_url, image_field))

        mock_ensure_dir.assert_called_once_with('output/images/farfetch/2024-01-01/12345')
        mock_rules.get_pdp_subfolder.assert_called_once_with(pdp_url)
        assert len(requests) == 2
        assert requests[0].url == image_field[0]
        assert requests[1].url == image_field[1]
        assert requests[0].callback == spider.save_image
        assert requests[1].callback == spider.save_image
        assert requests[0].meta['image_dir'] == 'output/images/farfetch/2024-01-01/12345'
        assert requests[1].meta['image_dir'] == 'output/images/farfetch/2024-01-01/12345'

    @patch('ecommercecrawl.spiders.farfetch_crawl.rules')
    @patch('ecommercecrawl.spiders.farfetch_crawl.FFSpider.ensure_dir')
    def test_download_images_empty_field(self, mock_ensure_dir, mock_rules):
        """
        Tests download_images with an empty image_field.
        """
        spider = FFSpider()
        date_string = "2024-01-01"
        pdp_url = "https://www.farfetch.com/item/12345.aspx"
        image_field = None

        requests = list(spider.download_images(date_string, pdp_url, image_field))

        mock_ensure_dir.assert_called_once()
        mock_rules.get_pdp_subfolder.assert_called_once_with(pdp_url)
        assert len(requests) == 0