# Ecommerce Crawler for Luxury Fashion Websites

This project contains Scrapy-based spiders designed to crawl and extract product data from luxury fashion websites, currently supporting Farfetch and Ounass.

## Project Structure

The project is organized to separate the crawling logic from the data extraction rules, making it more modular and easier to maintain.

-   `ecommercecrawl/spiders/`: This directory contains the Scrapy spiders. Each spider is responsible for navigating a target website and identifying product pages to be scraped.

-   `ecommercecrawl/rules/`: This directory holds the data extraction logic. For each website, there is a corresponding "rules" file that contains functions to extract specific pieces of data (e.g., product name, price, brand) from a product page response.

-   `ecommercecrawl/xpaths/`: This directory contains the XPath expressions used by the rules files. Centralizing the XPaths makes them easier to find and update when a website's structure changes.

-   `tests/`: This directory contains all the tests for the project. It includes unit tests for the data extraction logic and integration tests that use HTML fixtures to simulate real-world scraping scenarios.

## Spiders

-   **`farfetch_crawl`**: Crawls `farfetch.com`, extracts product data from product detail pages (PDPs), and follows pagination to discover more products.

-   **`ounass_crawl`**: Crawls `ounass.com` with similar functionality to the Farfetch spider.

---

## Maintenance: Updating Scraper Rules

Web scrapers are brittle by nature. The rules they use to extract data (like XPaths) are tied to the structure of the target website. When the website's layout changes, the scraper will break. This guide outlines the process for diagnosing and fixing failures in the Farfetch scraper.

### Symptom of a Broken Scraper

You will most likely discover a broken scraper when the tests for the rule functions fail. Specifically, you will see `AssertionError` in the output of `pytest tests/test_farfetch_rules.py`.

The error will typically show that a function returned `None` or an empty list (`[]`) instead of the expected data. This happens because the XPath used by the function could not find a match in the test's HTML fixture.

### How to Fix a Broken Scraper

Follow these steps to update the scraper and get the tests passing again.

**1. Download Fresh HTML**

To verify that the website's structure has changed, you need a fresh copy of the HTML from a live product page.

1.  Open your web browser and navigate to a Product Detail Page (PDP) on `farfetch.com`.
2.  Save the entire page by right-clicking and selecting "Save Page As..." or "Save as...".
3.  In the format dropdown, make sure to select **"Webpage, Complete"**. This will save a `.html` file and a folder containing all the page's assets (images, CSS, etc.).

**2. Update the Test Fixture**

Our tests use a static HTML file to ensure they are fast and repeatable. You need to update this fixture with the new HTML you just downloaded.

1.  Locate the `.html` file you saved.
2.  Open it in a text editor and copy its entire content.
3.  Paste the content into `tests/farfetch_html_fixtures/pdp.html`, completely replacing the old content.

**3. Identify the New XPaths**

Now, you need to find the new XPaths for the data that is failing to be extracted.

1.  Open the newly updated `tests/farfetch_html_fixtures/pdp.html` file in your web browser.
2.  Right-click on the piece of data you need to extract (e.g., the product's name) and select "Inspect" to open the browser's developer tools.
3.  In the Elements panel, you will see the HTML for the page. The element you clicked on will be highlighted.
4.  Right-click on the highlighted HTML element and choose "Copy" -> **"Copy XPath"**.
5.  Compare this newly copied XPath to the corresponding one in `ecommercecrawl/xpaths/farfetch_xpaths.py`. If it's different, update the XPath in the Python file.

**4. Update Expected Values in Tests**

Since you've updated the HTML fixture with a new product, the expected values in your tests (like the product name and brand) are now incorrect.

1.  Look at the new product page in your browser and note the correct values for the data being extracted.
2.  Open `tests/test_farfetch_rules.py` and update the assertion values in the failing tests to match the new product's data. For example, if the new product is a "Gucci" bag, change `assert rules.get_brand(pdp_response) == 'Christopher Esber'` to `assert rules.get_brand(pdp_response) == 'Gucci'`.

**5. Rerun the Tests**

Once you have updated the XPaths and the expected values in the tests, run the test suite again:

```bash
pytest tests/test_farfetch_rules.py
```

If all tests pass, you have successfully updated the scraper!