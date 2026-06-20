import json
import re
from typing import Optional, List
from ..types import DetailListing, DetailImage
from ..scraper.resolver import parse_page_model


def extract_detail_listing(html: str) -> DetailListing:
    page_model = _find_page_model(html)
    ctx = parse_page_model(page_model)

    arr        = ctx['arr']
    get        = ctx['get']
    get_schema = ctx['get_schema']
    res        = ctx['resolve']

    prices          = get_schema('prices')
    price_raw       = res(prices.get('primaryPrice'))
    price_qualifier = res(prices.get('displayPriceQualifier'))

    addr    = get_schema('address')
    outcode = _str(res(addr.get('outcode')))
    incode  = _str(res(addr.get('incode')))

    loc = get_schema('location')

    text      = get_schema('text')
    desc_html = res(text.get('description'))
    desc_text = _strip_html(desc_html) if isinstance(desc_html, str) else None

    images: List[DetailImage] = []
    raw_image_refs = ctx['schema'].get('images')
    if isinstance(raw_image_refs, int):
        image_index_list = arr[raw_image_refs]
        if isinstance(image_index_list, list):
            for position, img_ref in enumerate(image_index_list):
                if not isinstance(img_ref, int) or img_ref >= len(arr):
                    continue
                img_schema = arr[img_ref]
                if not isinstance(img_schema, dict):
                    continue

                url_base    = _str(res(img_schema.get('url')))
                resized_ref = img_schema.get('resizedImageUrls')
                resized     = arr[resized_ref] if isinstance(resized_ref, int) and resized_ref < len(arr) else None

                images.append(DetailImage(
                    position=position,
                    url_base=url_base,
                    url_large=_str(res(resized.get('size656x437'))) if isinstance(resized, dict) else None,
                    url_medium=_str(res(resized.get('size476x317'))) if isinstance(resized, dict) else None,
                    url_thumbnail=_str(res(resized.get('size135x100'))) if isinstance(resized, dict) else None,
                    caption=_str(res(img_schema.get('caption'))),
                ))

    cust = get_schema('customer')

    status  = get_schema('status')
    is_pub  = res(status.get('published'))
    is_arch = res(status.get('archived'))

    price_int = _parse_price(price_raw) if isinstance(price_raw, str) else None

    return DetailListing(
        listing_id=_str(get('id')),
        enc_id=_str(get('encId')),
        price=price_int,
        price_raw=price_raw if isinstance(price_raw, str) else None,
        price_qualifier=price_qualifier if isinstance(price_qualifier, str) else '',
        outcode=outcode,
        incode=incode,
        full_postcode=f'{outcode} {incode}' if outcode and incode else None,
        country_code=_str(res(addr.get('countryCode'))),
        uk_country=_str(res(addr.get('ukCountry'))),
        latitude=_float(res(loc.get('latitude'))),
        longitude=_float(res(loc.get('longitude'))),
        description_html=desc_html if isinstance(desc_html, str) else None,
        description_text=desc_text,
        images=images,
        agent_branch_id=_int(res(cust.get('branchId'))),
        agent_branch_name=_str(res(cust.get('branchName'))),
        agent_branch_display_name=_str(res(cust.get('branchDisplayName'))),
        agent_company_name=_str(res(cust.get('companyName'))),
        agent_company_trading_name=_str(res(cust.get('companyTradingName'))),
        agent_display_address=_str(res(cust.get('displayAddress'))),
        agent_profile_url=_str(res(cust.get('customerProfileUrl'))),
        agent_logo_path=_str(res(cust.get('logoPath'))),
        is_published=is_pub if isinstance(is_pub, bool) else None,
        is_archived=is_arch if isinstance(is_arch, bool) else None,
        property_sub_type=_str(get('propertySubType')),
        bedrooms=_int(get('bedrooms')),
        bathrooms=_int(get('bathrooms')),
    )



def _find_page_model(html: str) -> dict:
    markers = [
        'window.__PAGE_MODEL = ',
        'window.__PAGE_MODEL=',
        'window.PAGE_MODEL = ',
        'window.PAGE_MODEL=',
    ]

    marker_end = -1
    for marker in markers:
        idx = html.find(marker)
        if idx != -1:
            marker_end = idx + len(marker)
            break

    if marker_end == -1:
        raise ValueError(
            '__PAGE_MODEL not found in page HTML. '
            'Possible causes: missing session cookies, CAPTCHA, or '
            'Rightmove changed their page structure.'
        )

    json_start = html.find('{', marker_end)
    if json_start == -1:
        raise ValueError('No JSON object found after __PAGE_MODEL marker')

    try:
        
        obj, _ = json.JSONDecoder().raw_decode(html, json_start)
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(f'Failed to parse __PAGE_MODEL__ JSON: {e}')


def _parse_price(raw: str) -> Optional[int]:
    cleaned = re.sub(r'[£,\s]', '', raw)
    try:
        return int(cleaned)
    except ValueError:
        return None


def _strip_html(html: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    for old, new in [
        ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' '),
        ('\\u003C', '<'), ('\\u003E', '>'),
    ]:
        text = text.replace(old, new)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _str(v) -> Optional[str]:
    return v if isinstance(v, str) and v else None

def _int(v) -> Optional[int]:
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None

def _float(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None