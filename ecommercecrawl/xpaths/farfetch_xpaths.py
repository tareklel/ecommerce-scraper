PAGINATION_XPATH = "//div[@data-component='Pagination']//span[@data-component='PaginationLabel']/text()"
# need to try again xpath for test
PDP_XPATH = """
    //li[@data-testid='productCard' and not(ancestor::*[@data-component='ProductShowcase'])]
    //a[contains(@href, '/shopping/') and contains(@href, 'item-') and contains(@href, '.aspx')]/@href
"""
PRICE_XPATH = "string(//meta[@property='twitter:data1']/@content)"
BREADCRUMBS_XPATH = '//li[@data-component="BreadcrumbWrapper"]/a/text()'
PRODUCT_NAME_XPATH = 'normalize-space(string(//p[@data-testid="product-short-description"][1]))'
IMAGE_XPATH = '//img[@data-component="Image"]/@src'
BRAND_XPATH = '//a[@data-ffref="pp_infobrd"]/text()'
DISCOUNT_XPATH = '//p[@data-component="PriceDiscount"]/text()'
PRIMARY_LABEL_XPATH = '//p[@data-component="LabelPrimary"]/text()'
IMAGE_URL_XPATH = "string(//meta[@property='og:image']/@content)"
#extracts Highlights and Composition text
HIGHLIGHTS_XPATH = '//h4[normalize-space(.)="Highlights"]/following-sibling::ul[1]//li/text()'
COMPOSITION_XPATH = 'normalize-space(string(//h4[normalize-space(.)="Composition"]/following-sibling::p[1]))'
PLP_XPATH = '//script[@type="application/ld+json" and contains(., \'\"@type\":\"ItemList\"\')]/text()'