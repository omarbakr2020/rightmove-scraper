import json
import re
from typing import List
from ..types import SearchListing, SearchImage


def extract_search_listings(html: str) -> List[SearchListing]:
    next_data = _parse_next_data(html)
    if not next_data:
        return []

    try:
        properties = next_data['props']['pageProps']['searchResults']['properties']
    except (KeyError, TypeError):
        return []

    listings = []
    for prop in properties:
        listing_id = prop.get('id')

        if not isinstance(listing_id, int) or listing_id > 999_999_999:
            continue

        customer       = prop.get('customer') or {}
        location       = prop.get('location') or {}
        price_data     = prop.get('price') or {}
        tenure         = prop.get('tenure') or {}
        property_imgs  = prop.get('propertyImages') or {}
        listing_update = prop.get('listingUpdate') or {}

        raw_features = prop.get('keyFeatures') or []
        key_features = [
            f['description']
            for f in sorted(raw_features, key=lambda x: x.get('order', 0))
            if f.get('description')
        ]

        
        images = [
            SearchImage(
                position=i,
                url_base=img.get('url'),
                caption=img.get('caption'),
            )
            for i, img in enumerate(property_imgs.get('images') or [])
        ]

        raw_url = prop.get('propertyUrl', '')
        clean_path = raw_url.split('#')[0]

        listings.append(SearchListing(
            id=str(listing_id),
            url=f'https://www.rightmove.co.uk{clean_path}',
            display_address=prop.get('displayAddress'),
            price=price_data.get('amount'),
            price_currency=price_data.get('currencyCode', 'GBP'),
            property_sub_type=prop.get('propertySubType'),
            bedrooms=prop.get('bedrooms'),
            bathrooms=prop.get('bathrooms'),
            latitude=location.get('latitude'),
            longitude=location.get('longitude'),
            agent_branch_id=customer.get('branchId'),
            agent_branch_display_name=customer.get('branchDisplayName'),
            agent_branch_name=customer.get('branchName'),
            agent_phone=customer.get('contactTelephone'),
            agent_logo_uri=customer.get('brandPlusLogoURI'),
            tenure_type=tenure.get('tenureType'),
            summary=prop.get('summary'),
            key_features=key_features,
            images=images,
            added_or_reduced=prop.get('addedOrReduced'),
            listing_update_reason=listing_update.get('listingUpdateReason'),
            listing_update_date=listing_update.get('listingUpdateDate'),
        ))

    return listings


def extract_pagination(html: str) -> dict:
    next_data = _parse_next_data(html)
    if not next_data:
        return {'last': 0, 'page_size': 24, 'result_count': '0'}

    try:
        results    = next_data['props']['pageProps']['searchResults']
        pagination = results.get('pagination', {})
        params     = results.get('searchParameters', {})
        count      = results.get('resultCount', '0')
    except (KeyError, TypeError):
        return {'last': 0, 'page_size': 24, 'result_count': '0'}

    return {
        'last':         int(pagination.get('last', 0)),
        'page_size':    int(params.get('numberOfPropertiesPerPage', 24)),
        'result_count': count,
    }


def _parse_next_data(html: str):
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
