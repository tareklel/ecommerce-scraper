PAGINATION_XPATH = '//span[@data-component="PaginationLabel"]/text()'
PDP_XPATH = '//a[@data-component="ProductCardLink"]/@href'
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